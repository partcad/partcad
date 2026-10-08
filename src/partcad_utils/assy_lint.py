#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Position-accurate syntax and schema checking for PartCAD's YAML documents.

PartCAD writes two kinds of them, and they are the same kind of document: an
ASSY file (``*.assy``) and a package configuration (``partcad.yaml``) are both
Jinja2 templates that are rendered into YAML and then have to conform to a JSON
schema. (``partcad.yaml`` is rendered by `ProjectLocal`, with an
``includePaths`` of its own to pull fragments in.) That is three error classes a
user can hit in either of them -- a broken template, YAML that does not parse,
and YAML that parses but does not match the schema -- and an editor is only
useful if it can point at the *source* line of each one.

Which schema governs a file is `schema_for_file`, and it is the only thing that
differs between the two: everything below is about the shape they share.

**A file is checked as it renders.** What PartCAD reads is the rendering -- the
items a loop produces, the branch an ``{% if %}`` takes, the number an
expression comes to -- so that is what is checked, with the values PartCAD
renders it with: an ASSY file's parameters as its declaration defaults them, a
``partcad.yaml``'s version and constants (see `Render`, and
'partcad_utils.lint_context', which works the values out). Every finding is then
put back on the line and column of the template it came from, which is what
'partcad_utils.template_render' keeps the way back for: literal text maps to
itself, what an expression produced to its ``{{ }}``, a loop's every pass to its
body. A template that raises with those values -- an undefined name, a division
by zero, a template that calls an undefined function on purpose to stop with a
message -- is an error on the line it raised on, because PartCAD would stop
there too.

**A file nothing declares is checked masked.** Its values are not known (it is
being written, or belongs to no package yet), and rendering it with none would
report every parameter as missing. So the template is masked instead: every
Jinja2 construct is replaced, in place, with an equally sized run of inert
characters:

  * ``{{ expr }}`` becomes a filler scalar, so a templated value stays a value,
  * ``{% tag %}`` and ``{# comment #}`` become blanks, so a control-flow line
    stays an empty line, and a loop or conditional body is checked once,
  * a ``{{ expr }}`` alone on its line, an ``{% include %}`` and a
    ``{% call %}`` block become blanks too, and count as unknown both as a value
    and as keys. What each stands for is lines of YAML -- a macro's output, a
    fragment kept in a variable, another file -- or none at all (a template
    that calls an undefined function to stop with a message); a filler scalar
    in their place turned the next key into "mapping values are not allowed
    here",
  * the body of a ``{% macro %}`` or of a block ``{% set %}`` becomes blanks:
    it renders nothing where it is written.

Newlines inside a construct are preserved, so the masked document has exactly
the same line and column layout as the file on disk: a YAML parse error, or a
schema violation resolved through the composed YAML node tree, lands on the
character the user actually wrote.

Masking necessarily loses information -- what a ``{{ expr }}`` evaluates to, and
which branch of a ``{% if %}`` is taken -- so any finding that depends on that
lost information is dropped rather than reported. That trades a missed error for
never underlining correct code, which is the right trade for an editor, and is
why masking is the fallback rather than the check.

Beside the schema, two things are checked that no schema can say: a link named
by a ``connect:`` that nothing places ('check_links'), and, for what is marked
manufacturable, an assembly item that is placed rather than connected and a part
that nobody could make or buy ('check_manufacturable_assembly',
'check_manufacturable_parts').

It lives here, next to ``framing`` and ``workspace``, because neither end owns
it. The daemon checks a package's files when `pc lint` walks the package graph;
every client checks the one file somebody is editing, in its own process
(`partcad_client.lint`). Both are answering the same question about the same
documents, so a copy on each side is a copy that can disagree -- and a
disagreement here means the editor and CI contradicting each other about a file.
Nothing in this module needs a loaded PartCAD context, or ``partcad`` at all --
which is why both schemas are packaged beside it rather than under ``partcad``,
where reaching one would import the CAD kernel to read a JSON file.
"""

import copy
import json
import os
import re
from importlib import resources

import jinja2
import jsonschema
import jsonschema.exceptions
import yaml

from . import assy_filter, template_render

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# Source of every diagnostic produced here, so editors can group them.
SOURCE = "partcad"

# Diagnostic codes, reported alongside the message.
CODE_TEMPLATE = "jinja2"
CODE_YAML = "yaml"
CODE_SCHEMA = "schema"
# A link that is named but not placed: what the schema cannot see, because it
# is a relation between two parts of one document rather than the shape of
# either. See 'check_links()'.
CODE_LINKS = "links"
# Something marked manufacturable that nobody could make: an item of an assembly
# placed by coordinates rather than connected, a part with no way to be had.
# See 'check_manufacturable_assembly()' and 'check_manufacturable_parts()'.
CODE_MANUFACTURABLE = "manufacturable"

# Kinds of masked region. They differ in what they are allowed to suppress:
# an expression stands in for a *value*, a statement can add or remove *keys*.
_EXPR = "expr"
_STMT = "stmt"

# The character a masked '{{ expr }}' is replaced with. Any run of it is a plain
# YAML scalar in every context, which is what keeps the masked document parsable.
_FILL = "x"

_DELIMITERS = (
    ("{{", "}}", _EXPR),
    ("{%", "%}", _STMT),
    ("{#", "#}", _STMT),
)

# Schema violations that are about the *value* at a location. They are dropped
# when a template expression produced that value, because the real value is
# whatever the expression evaluates to, not the filler standing in for it.
_VALUE_VALIDATORS = frozenset(
    {
        "type",
        "enum",
        "const",
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "items",
        "additionalItems",
    }
)

# Schema violations that are about which *keys* are present. They are dropped
# when a Jinja2 statement lives inside the offending block, because the keys the
# statement contributes are only known after rendering.
_KEY_VALIDATORS = frozenset({"required", "anyOf", "oneOf", "not", "dependencies"})

ASSY_SCHEMA = "assy.json"
PARTCAD_SCHEMA = "partcad.json"

# What governs a file, by name and then by extension. A package configuration is
# recognised by its whole filename because that is what makes it one: PartCAD
# looks for `partcad.yaml` by name, and a `parts.yaml` beside it is somebody's
# own file that nothing here should have an opinion about.
#
# Both lookups are case-insensitive, so a `Logo.ASSY` or a `PartCAD.yaml` on a
# case-insensitive filesystem is checked rather than silently skipped -- the
# package walk and the editor have to agree about which files are checked at all,
# not only about what they say.
_SCHEMA_BY_FILENAME = {
    "partcad.yaml": PARTCAD_SCHEMA,
}
_SCHEMA_BY_EXTENSION = {
    ".assy": ASSY_SCHEMA,
}

# What an ASSY file is being read as. The same document means slightly
# different things depending on which section of a package points at it:
#
#   FLAVOR_ASSEMBLY -- an entry in `assemblies:`. The full ASSY schema.
#   FLAVOR_SCENE    -- an entry in `scenes:`. The same schema with `how`
#                      forbidden: a scene states where things are, not how they
#                      got there (see `partcad.scene`).
#
# Which one a given file is is not a property of the file, so nothing here can
# work it out; the caller says, and both callers answer it best effort (see
# `partcad_client.lint.detect_flavor` and the extension's `PartcadLint`).
FLAVOR_ASSEMBLY = "assembly"
FLAVOR_SCENE = "scene"
FLAVORS = (FLAVOR_ASSEMBLY, FLAVOR_SCENE)

# What a scene is told when it declares assembly instructions. Carried in the
# schema so that the one finding reads the same in the editor, in `pc lint` and
# in `pc lint --file`; `_describe()` is what puts it in front of the user.
SCENE_NO_HOW = (
    "'how' is not allowed in a scene: a scene states where things are, "
    "not how they got there. Declare it in an assembly instead"
)

# What this checker is, for a cache key to hash.
#
# A cached finding for an unchanged file is only valid while the thing that
# produced it is the same. The schema is already half of that and is hashed
# (see 'lint/schema.py'); this is the other half -- the checks that are not in
# any schema. Bump it whenever a check is added, removed or changed, or the
# findings a package was linted with before the change go on being reported
# after it.
#
#   1 -- the template, YAML and schema checks.
#   2 -- 'check_links': a 'connect:' or an 'interferes:' naming a link nothing
#        places.
#   3 -- the document is checked as it renders, not masked, wherever the values
#        it is rendered with are known; and the two rules for what is marked
#        manufacturable.
CHECKER_VERSION = 3

# An upper bound on how many findings a single file reports. A file that is
# mid-edit can cascade; an editor gains nothing from the thousandth squiggle.
MAX_DIAGNOSTICS = 100

_schema_cache = {}


class Diagnostic:
    """One finding, positioned with zero-based LSP-style line/column numbers."""

    def __init__(self, severity, message, line, column, end_line=None, end_column=None, code=None, path=None):
        self.severity = severity
        self.message = message
        self.line = max(0, line)
        self.column = max(0, column)
        self.end_line = self.line if end_line is None else max(self.line, end_line)
        self.end_column = self.column + 1 if end_column is None else end_column
        if self.end_line == self.line and self.end_column <= self.column:
            self.end_column = self.column + 1
        self.code = code
        self.path = path

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "endLine": self.end_line,
            "endColumn": self.end_column,
            "source": SOURCE,
            "code": self.code,
            "path": self.path,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Diagnostic(%s, %d:%d, %r)" % (self.severity, self.line, self.column, self.message)

    def format(self, filename: str = None) -> str:
        """Render as the usual 'file:line:column: message' one-liner (1-based)."""
        where = "%s:%d:%d" % (filename or "", self.line + 1, self.column + 1)
        return "%s: %s" % (where.lstrip(":"), self.message)


# ---- schema loading --------------------------------------------------------


def get_schema(filename: str) -> dict:
    """Load and cache one of the JSON schemas shipped in ``partcad_utils.schema``."""
    if filename not in _schema_cache:
        with resources.files("partcad_utils.schema").joinpath(filename).open("r") as f:
            _schema_cache[filename] = json.load(f)
    return _schema_cache[filename]


def schema_name_for_file(path: str):
    """Return the schema filename that governs ``path``, or None if unknown."""
    name = os.path.basename(path).lower()
    if name in _SCHEMA_BY_FILENAME:
        return _SCHEMA_BY_FILENAME[name]
    return _SCHEMA_BY_EXTENSION.get(os.path.splitext(name)[1])


def is_assy_file(path: str) -> bool:
    """Whether ``path`` is an ASSY file, and so has an assembly/scene flavor.

    A `partcad.yaml` has one schema and no flavor: nothing points at a package
    configuration the way an `assemblies:` or a `scenes:` entry points at an
    ASSY file. Callers that work a flavor out ask this first, so that they do
    not spend the search -- or report an answer -- for a file it cannot apply to.
    """
    return schema_name_for_file(path) == ASSY_SCHEMA


def scene_schema(schema: dict) -> dict:
    """The scene-simplified ASSY schema: ``schema`` with ``how`` forbidden.

    Derived from the assembly schema rather than kept beside it as a second
    file. The two documents are the same format read for two purposes, and a
    copy of one is a copy that stops matching the other -- every field added to
    a ``connect:`` would have to be added twice, and the day one of them was
    missed an editor and CI would disagree about a file, which is the whole
    thing this module exists to prevent.

    ``how`` is *forbidden* rather than dropped: dropping it would leave
    ``additionalProperties: false`` to report an "unexpected property", which
    reads like a typo. It is not a typo -- it is a section that means something
    and belongs in an assembly -- and 'SCENE_NO_HOW' is what says so.
    """
    forbidden = {"not": {}, "description": SCENE_NO_HOW}
    result = copy.deepcopy(schema)
    definitions = result.get("definitions", {})
    for name in ("connect", "connectPorts"):
        properties = definitions.get(name, {}).get("properties")
        if isinstance(properties, dict) and "how" in properties:
            properties["how"] = forbidden
    definitions.pop("how", None)
    result["title"] = "PartCAD Scene YAML (ASSY)"
    return result


def schema_for_file(path: str, flavor: str = FLAVOR_ASSEMBLY):
    """The schema that governs ``path`` when read as ``flavor``, or None.

    ``flavor`` only means anything for an ASSY file; it is ignored for a
    `partcad.yaml`, which has one schema. A caller that passes one anyway (an
    editor sending the same parameters for every document, `pc lint --file
    --schema scene` naming a configuration by mistake) gets the configuration
    schema rather than a scene-flavored derivative of it, which would be a
    schema forbidding a `how` no package configuration has.
    """
    name = schema_name_for_file(path)
    if name is None:
        return None
    if flavor != FLAVOR_SCENE or name != ASSY_SCHEMA:
        return get_schema(name)
    # Cached like the file-backed schemas beside it: an editor checks the same
    # document on every keystroke, and deriving it each time would deep-copy
    # the whole schema for nothing.
    key = (name, FLAVOR_SCENE)
    if key not in _schema_cache:
        _schema_cache[key] = scene_schema(get_schema(name))
    return _schema_cache[key]


# ---- Jinja2 masking --------------------------------------------------------


class _Masked:
    """The masked text plus the positions the mask covers."""

    def __init__(self, text, spans):
        self.text = text
        # [(start, end, kind)] with positions as (line, column) tuples.
        self.spans = spans

    def overlaps(self, start, end, kind=None) -> bool:
        for span_start, span_end, span_kind in self.spans:
            if kind is not None and span_kind != kind:
                continue
            if span_start < end and start < span_end:
                return True
        return False


def _line_starts(text: str):
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _to_position(line_starts, offset: int):
    # Binary search would be tidier; files here are small enough that the
    # linear walk from a bisect is not worth the import.
    low, high = 0, len(line_starts) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if line_starts[middle] <= offset:
            low = middle
        else:
            high = middle - 1
    return (low, offset - line_starts[low])


def _blank_like(chunk: str, kind: str) -> str:
    """Replace ``chunk`` with inert characters of the same shape."""
    lines = chunk.split("\n")
    filler = _FILL if kind == _EXPR else " "
    masked = [filler * len(lines[0])]
    # A construct that spans lines can only stand in for a value on its first
    # line; the continuation lines become whitespace so the YAML layout holds.
    masked.extend(" " * len(line) for line in lines[1:])
    return "\n".join(masked)


def mask_template(text: str) -> _Masked:
    """Replace every Jinja2 construct in ``text`` with same-sized filler."""
    line_starts = _line_starts(text)
    out = []
    spans = []
    index = 0
    while index < len(text):
        found = None
        for opening, closing, kind in _DELIMITERS:
            at = text.find(opening, index)
            if at != -1 and (found is None or at < found[0]):
                found = (at, opening, closing, kind)
        if found is None:
            out.append(text[index:])
            break
        at, opening, closing, kind = found
        end = text.find(closing, at + len(opening))
        if end == -1:
            # Unterminated. `check_template()` reports it with the exact line;
            # there is nothing sensible left to mask.
            out.append(text[index:])
            break
        end += len(closing)
        tag = _TAG.match(text, at) if opening == "{%" else None
        tag = tag.group(1) if tag else None
        renders_lines = (kind == _EXPR and _alone_on_its_lines(text, at, end)) or tag in ("include", "call")
        if tag in _BODY_TAGS and (tag != "set" or "=" not in text[at:end]):
            # A macro or a block `set` renders nothing where it stands, and a
            # `call` renders the macro's output: either way its body is not
            # YAML at this place, so all of it goes, up to the closing tag.
            end = _end_of_block(text, end, tag)
        out.append(text[index:at])
        start_position, end_position = _to_position(line_starts, at), _to_position(line_starts, end)
        if renders_lines:
            # Lines of YAML, or none: it may supply a value, keys or items, so it
            # is both kinds of unknown.
            out.append(_blank_like(text[at:end], _STMT))
            spans.append((start_position, end_position, _EXPR))
            spans.append((start_position, end_position, _STMT))
        else:
            out.append(_blank_like(text[at:end], kind))
            spans.append((start_position, end_position, kind))
        index = end
    return _Masked("".join(out), spans)


# The name of a `{% tag %}`, and the tags whose body is not YAML where it stands.
_TAG = re.compile(r"\{%[-+]?\s*(\w+)")
_BODY_TAGS = ("macro", "call", "set")


def _end_of_block(text: str, index: int, tag: str) -> int:
    """Where the `{% end<tag> %}` closing a block opened just before ``index`` ends.

    Blocks of the same tag nest. A block that is never closed is a template
    error `check_template()` has already reported, and the masking never runs
    for it -- but if it does, only the opening tag is masked.
    """
    pattern = re.compile(r"\{%[-+]?\s*(end)?" + tag + r"\b[^%]*(?:%(?!\})[^%]*)*[-+]?%\}")
    depth = 1
    for match in pattern.finditer(text, index):
        if match.group(1):
            depth -= 1
            if depth == 0:
                return match.end()
        elif tag != "set" or "=" not in match.group(0):
            depth += 1
    return index


def _alone_on_its_lines(text: str, start: int, end: int) -> bool:
    """Whether nothing but whitespace shares the lines ``text[start:end]`` is on."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return not text[line_start:start].strip() and not text[end:line_end].strip()


def check_template(text: str) -> list:
    """Report Jinja2 syntax errors (unbalanced blocks, unknown tags, ...)."""
    try:
        # Parsing only builds the AST: no template is loaded, nothing is
        # evaluated, and no parameter value is needed.
        jinja2.Environment().parse(text)
    except jinja2.TemplateSyntaxError as exc:
        line = (exc.lineno or 1) - 1
        return [
            Diagnostic(
                SEVERITY_ERROR,
                "Jinja2 template error: %s" % exc.message,
                line,
                0,
                end_line=line,
                end_column=_line_length(text, line),
                code=CODE_TEMPLATE,
            )
        ]
    except Exception as exc:  # pylint: disable=broad-except
        return [
            Diagnostic(
                SEVERITY_ERROR,
                "Jinja2 template error: %s" % exc,
                0,
                0,
                code=CODE_TEMPLATE,
            )
        ]
    return []


def _line_length(text: str, line: int) -> int:
    lines = text.split("\n")
    return len(lines[line]) if 0 <= line < len(lines) else 1


# ---- YAML -> position mapping ----------------------------------------------


def _node_span(node):
    """The span of a node's actual content, as (start, end) (line, column) pairs.

    Not ``start_mark``/``end_mark``: a block collection's ``end_mark`` runs to
    the start of whatever token follows, so it swallows the blank lines and the
    (masked) ``{% endfor %}`` after it. That both over-reports the range to
    underline and, worse, would make every node that merely *precedes* a Jinja2
    tag look like it contains one.
    """
    if isinstance(node, yaml.MappingNode) and node.value:
        first_key, _ = node.value[0]
        last_key, last_value = node.value[-1]
        return _node_span(first_key)[0], _node_span(last_value if last_value is not None else last_key)[1]
    if isinstance(node, yaml.SequenceNode) and node.value:
        return _node_span(node.value[0])[0], _node_span(node.value[-1])[1]
    return (node.start_mark.line, node.start_mark.column), (node.end_mark.line, node.end_mark.column)


def _child(node, key):
    """Descend one step of a JSON path through a composed YAML node tree."""
    if isinstance(node, yaml.SequenceNode) and isinstance(key, int):
        if 0 <= key < len(node.value):
            return node.value[key]
    elif isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if str(key_node.value) == str(key):
                return value_node
    return None


def _resolve(root, path):
    """Return the deepest node reachable along ``path``, never None if root isn't."""
    node = root
    for key in path:
        child = _child(node, key)
        if child is None:
            return node
        node = child
    return node


def _key_node(node, key):
    if isinstance(node, yaml.MappingNode):
        for key_node, _ in node.value:
            if str(key_node.value) == str(key):
                return key_node
    return None


# ---- schema violations -----------------------------------------------------


# The 'expression' definition's pattern in 'partcad.json'. Named here so that a
# failure against it can be reported as what it means rather than as a regex.
EXPRESSION_PATTERN = "^%[^%]+%$"


def _quoted(names) -> str:
    return ", ".join("'%s'" % name for name in names)


def _required_only(subschemas):
    """The key names of an anyOf/oneOf whose branches are all bare 'required'."""
    names = []
    for subschema in subschemas or []:
        if not isinstance(subschema, dict) or set(subschema) != {"required"}:
            return None
        names.extend(subschema["required"])
    return names or None


def _unexpected_keys(error) -> list:
    """The property names an 'additionalProperties: false' error is about."""
    schema = error.schema if isinstance(error.schema, dict) else {}
    allowed = set(schema.get("properties", {}))
    patterns = list(schema.get("patternProperties", {}))
    unexpected = []
    for key in error.instance if isinstance(error.instance, dict) else []:
        if key in allowed:
            continue
        if any(re.search(pattern, str(key)) for pattern in patterns):
            continue
        unexpected.append(key)
    return unexpected


def _most_specific(error):
    """Descend into a failed anyOf/oneOf for the most informative sub-error.

    ``best_match`` is handed the error itself rather than its ``context``, which
    is what makes it descend: given a list it takes the *most* relevant member
    and then walks down through that member's own branches, discarding a branch
    only when two of them are equally plausible. Given a ``context`` it took the
    least relevant of the alternatives instead -- so a part declaration failing
    the `oneOf` of "a path string" and "a declaration object" was reported
    against the string branch, and a bad ``axis`` came out as "is not of type
    'string'" rather than as "[1, 2] is too short".

    Answering the same way `jsonschema.validate()` does is the point: that is
    the wording `pc lint` printed for a `partcad.yaml` before this checker
    reported it, and the wording the schema's own error messages are written to.
    """
    return jsonschema.exceptions.best_match([error]) or error


def _describe(error):
    """Turn a jsonschema error into a message a user can act on.

    ``jsonschema``'s own wording for the combinators this schema leans on
    ("... is not valid under any of the given schemas", "... should not be valid
    under {'required': [...]}") says nothing about what to change, so the three
    shapes PartCAD's schemas use are spelled out here.
    """
    if error.validator == "not" and error.validator_value == {}:
        # A property the schema forbids outright, carrying its own explanation
        # (see 'scene_schema'). jsonschema would say "should not be valid under
        # {}", which tells the reader nothing about what to do.
        described = (error.schema or {}).get("description") if isinstance(error.schema, dict) else None
        if described:
            return described
    if error.validator == "not":
        forbidden = (error.validator_value or {}).get("required")
        if forbidden and len(forbidden) > 1:
            return "%s are mutually exclusive; use only one of them" % _quoted(forbidden)
    if error.validator in ("anyOf", "oneOf"):
        names = _required_only(error.validator_value)
        if names:
            return "expected at least one of %s" % _quoted(names)
    if error.validator == "pattern" and error.validator_value == EXPRESSION_PATTERN:
        # A string where a number or a '%...%' expression belongs. Every use of
        # the 'expression' definition is one branch of a 'oneOf' with a number,
        # and 'best_match' descends into that branch because the value is a
        # string - so jsonschema's own wording names only the pattern, and a
        # reader who wrote a plain word is told about a regular expression
        # rather than about the two things they could have written.
        return "%r is neither a number nor a '%%...%%' expression over the object's parameters" % (error.instance,)
    return error.message


def _validate_schema(data, schema, root_node, masked) -> list:
    """Validate ``data`` and place every violation on its source characters."""
    validator_class = jsonschema.validators.validator_for(schema)
    diagnostics = []

    for error in validator_class(schema).iter_errors(data):
        path = list(error.absolute_path)
        node = _resolve(root_node, path) if root_node is not None else None

        # Unexpected properties are reported per key, at the key, rather than as
        # one finding on the whole block: that is where the typo is.
        if error.validator == "additionalProperties":
            for key in _unexpected_keys(error):
                key_node = _key_node(node, key)
                start, end = _node_span(key_node) if key_node is not None else _fallback_span(node)
                if masked.overlaps(start, end, _EXPR):
                    # The property name itself came out of a template.
                    continue
                diagnostics.append(
                    Diagnostic(
                        SEVERITY_WARNING,
                        "unexpected property '%s'" % key,
                        start[0],
                        start[1],
                        end[0],
                        end[1],
                        code=CODE_SCHEMA,
                        path=error.json_path,
                    )
                )
            continue

        message = _describe(error)
        if message == error.message and error.context:
            # A generic combinator failure: the sub-error is more useful, and it
            # points deeper into the document.
            error = _most_specific(error)
            message = _describe(error)
            path = list(error.absolute_path)
            node = _resolve(root_node, path) if root_node is not None else None

        start, end = _node_span(node) if node is not None else ((0, 0), (0, 1))

        if error.validator == "not" and error.validator_value == {} and path and root_node is not None:
            # A property the schema forbids outright: underline the key, which
            # is what has to go, rather than the value under it.
            key_node = _key_node(_resolve(root_node, path[:-1]), path[-1])
            if key_node is not None:
                start, end = _node_span(key_node)

        # Drop what the mask made unknowable (see the module docstring).
        if error.validator in _VALUE_VALIDATORS and masked.overlaps(start, _reach(node, end, masked), _EXPR):
            continue
        if error.validator in _KEY_VALIDATORS and masked.overlaps(start, end, _STMT):
            continue

        diagnostics.append(
            Diagnostic(
                SEVERITY_ERROR,
                message,
                start[0],
                start[1],
                end[0],
                end[1],
                code=CODE_SCHEMA,
                path=error.json_path,
            )
        )

    return diagnostics


def _reach(node, end, masked):
    """Where the value at ``node`` could extend to once the template is rendered.

    Its own end, except for a key with nothing after it: YAML reads that as an
    empty value, and the lines up to the next thing YAML sees are where a
    template that renders lines -- an ``{% include %}``, a ``{{ macro() }}`` on
    a line of its own -- puts the value YAML did not see.
    """
    if not isinstance(node, yaml.ScalarNode) or node.value != "" or node.style is not None:
        return end
    line_starts = _line_starts(masked.text)
    offset = line_starts[end[0]] + end[1]
    while offset < len(masked.text) and masked.text[offset].isspace():
        offset += 1
    return _to_position(line_starts, offset)


def _fallback_span(node):
    if node is None:
        return ((0, 0), (0, 1))
    return _node_span(node)


# ---- links that nothing places ---------------------------------------------


# The two sections that place a node by relating it to another node of the same
# 'links:' list. They differ in what they name on each side -- an interface or a
# port -- and not at all in which link they connect *to*, which is 'name:' in
# both.
_CONNECT_SECTIONS = ("connect", "connectPorts")


def _all_link_names(node, found=None) -> set:
    """Every name this document gives a node, at any depth.

    What 'interferes:' is checked against. A connection names the further items
    one act of joining drives through, and those are matched by name across the
    assemblies an ASSY file embeds (see 'Assembly.connected_children()' and
    'partcad.test.interference'), so the whole document is the scope rather than
    one 'links:' list.
    """
    if found is None:
        found = set()
    if isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, dict):
                name = assy_filter.link_name(item, index)
                if name is not None:
                    found.add(name)
            _all_link_names(item, found)
        return found
    if not isinstance(node, dict):
        return found
    _all_link_names(node.get(assy_filter.LINKS) or [], found)
    return found


def check_links(data, root_node=None, masked=None) -> list:
    """Report a 'connect' or an 'interferes' that names a link nothing places.

    The schema cannot: it describes the shape of one node, and this is a
    relation between two of them. The relation is the whole point of a
    ``connect:`` -- it says which link already in the assembly this one is
    placed against -- and getting the name wrong is answered, when the assembly
    is eventually built, with "Target part not found" and a part at the origin.
    So it is checked here, where the file is, alongside everything else
    ``pc lint`` says about it.

    Three things are checked, and each of them is exactly what
    ``AssemblyFactoryAssy`` does with the value:

      * ``connect:``/``connectPorts:`` name a link of the **same** ``links:``
        list, and one written **before** this node -- the factory looks for it
        among the children placed so far, so a link named later is not there
        yet (see 'handle_node' and 'handle_node_list');
      * ``connect.interferes`` names a link of the document;
      * the root node has no ``connect:`` at all, having no sibling to connect
        to (see 'AssemblyFactoryAssy.apply_root_placement', which reports the
        same thing when the file is read).

    ``root_node`` is the composed YAML of the same text, used to put each
    finding on the character it is about, and ``masked`` the record of what
    Jinja2 stood in for. A finding that depends on what a template renders to is
    dropped rather than reported, for the reason the whole module gives: an
    editor that underlines correct code is worse than one that misses something.
    """
    diagnostics: list = []
    if not isinstance(data, dict):
        return diagnostics

    everywhere = _all_link_names(data)

    def report(path, message):
        node = _resolve(root_node, path) if root_node is not None else None
        start, end = _fallback_span(node)
        diagnostics.append(
            Diagnostic(
                SEVERITY_ERROR,
                message,
                start[0],
                start[1],
                end[0],
                end[1],
                code=CODE_LINKS,
                path="$." + ".".join(str(step) for step in path) if path else "$",
            )
        )

    def templated(path, kind=_EXPR) -> bool:
        """Whether a template stands where this value should be."""
        if masked is None or root_node is None:
            return False
        node = _resolve(root_node, path)
        if node is None:
            return False
        start, end = _node_span(node)
        # An empty value reaches to the next line YAML sees: see '_reach'.
        return masked.overlaps(start, _reach(node, end, masked), kind)

    # The root node is the assembly itself, so there is nothing beside it.
    for section in _CONNECT_SECTIONS:
        if data.get(section) is not None:
            report(
                [section],
                "the root node of an ASSY file is the assembly itself and has nothing to '%s' to" % section,
            )

    def level(node, path):
        links = node.get(assy_filter.LINKS)
        if not isinstance(links, list):
            return
        links_path = path + [assy_filter.LINKS]

        # A Jinja2 statement inside the list can add or remove items, so which
        # links this level places is only known after rendering.
        unknown = templated(links_path, _STMT)
        names = []
        for index, item in enumerate(links):
            name = assy_filter.link_name(item, index) if isinstance(item, dict) else None
            spelling = _name_key(item) if isinstance(item, dict) else None
            if name is not None and spelling is not None and templated(links_path + [index, spelling]):
                # A templated name: the set of names at this level is not known,
                # so nothing about it can be reported.
                unknown = True
            names.append(name)

        for index, item in enumerate(links):
            if not isinstance(item, dict):
                continue
            item_path = links_path + [index]
            if not unknown:
                _check_connect(item, item_path, names, index, everywhere, report, templated)
            level(item, item_path)

    level(data, [])
    return diagnostics


def _name_key(node):
    """Which key gave this node its name, so a finding can point at it.

    ``None`` for a node whose name is its position in the list: there is nothing
    in the file to point at, and nothing a template could have written there.
    """
    if node.get("name") is not None:
        return "name"
    for key in assy_filter.PLACES:
        if node.get(key) is not None:
            return key
    return None


def _check_connect(node, path, names, index, everywhere, report, templated) -> None:
    """Check one node's connection against the links beside it."""
    for section in _CONNECT_SECTIONS:
        connect = node.get(section)
        if not isinstance(connect, dict):
            continue
        target = connect.get("name")
        target_path = path + [section, "name"]
        if target is None:
            if templated(target_path) or templated(target_path, _STMT):
                # A 'name:' whose value is lines a template writes -- on the
                # line after it, say -- reads as empty when masked.
                continue
            report(
                path + [section],
                "'%s' does not say which link to connect to: it needs a 'name'" % section,
            )
        elif not templated(target_path):
            target = str(target)
            before = [name for name in names[:index] if name is not None]
            after = [name for name in names[index + 1 :] if name is not None]
            if target in before:
                pass
            elif target in after:
                report(
                    target_path,
                    "'%s' is placed after this node, so it is not there to be connected to yet; "
                    "move it above this node" % target,
                )
            elif target in everywhere:
                report(
                    target_path,
                    "'%s' is not a link of the same 'links:' list, so this node cannot be connected to it" % target,
                )
            else:
                report(target_path, "nothing in this file places a link called '%s'" % target)

        interferes = connect.get("interferes")
        if interferes is None:
            continue
        values = interferes if isinstance(interferes, list) else [interferes]
        for position, other in enumerate(values):
            if not isinstance(other, str):
                continue
            other_path = path + [section, "interferes"] + ([position] if isinstance(interferes, list) else [])
            if not templated(other_path) and other not in everywhere:
                report(other_path, "nothing in this file places a link called '%s'" % other)


# ---- what is to be made ----------------------------------------------------
#
# Two rules for what is marked 'manufacturable: true' -- on the object, on its
# package, or on a package above it. "Marked", not "is": PartCAD takes an
# object as manufacturable unless something says otherwise, and 'pc test'
# holds it to that, but a package nobody has said anything about yet is one
# being sketched, and an editor that underlined every part of it would be
# underlining work in progress. Saying 'manufacturable: true' -- which is what
# 'pc init' asks about -- is what turns these on.

_MANUFACTURED_CONNECTIONS = ("connect", "connectPorts")
_NOT_MADE_OF_ITS_OWN = ("alias", "enrich")


def _report_at(diagnostics, root_node, path, key, message):
    node = _resolve(root_node, path) if root_node is not None else None
    key_node = _key_node(node, key) if node is not None and key is not None else None
    start, end = _node_span(key_node) if key_node is not None else _fallback_span(node)
    diagnostics.append(
        Diagnostic(
            SEVERITY_ERROR,
            message,
            start[0],
            start[1],
            end[0],
            end[1],
            code=CODE_MANUFACTURABLE,
            path="$." + ".".join(str(step) for step in path + ([key] if key else [])),
        )
    )


def check_manufacturable_assembly(data, root_node=None) -> list:
    """Report an item of an assembly that is to be made that is not connected to anything.

    The same rule 'partcad.test.connectivity' holds a manufacturable assembly
    to, and in the same words, so that the editor and 'pc test' say one thing:
    somebody has to physically put this together, and a coordinate does not
    tell them anything they can act on -- it says where a part ends up, not
    what holds it there. So no item of any 'links:' list may say 'location:',
    and every item after the first has to say what it is joined to. The first
    item of a list is the one the others hang from, placed by being first. The
    document's own root -- the frame the whole assembly is in -- is not an item
    of anything, and may be placed.
    """
    diagnostics: list = []

    def level(node, path):
        links = node.get(assy_filter.LINKS)
        if not isinstance(links, list):
            return
        for index, item in enumerate(links):
            if not isinstance(item, dict):
                continue
            item_path = path + [assy_filter.LINKS, index]
            name = assy_filter.link_name(item, index)
            if "location" in item:
                _report_at(
                    diagnostics,
                    root_node,
                    item_path,
                    "location",
                    "'%s' is placed by coordinates, which says where it ends up but not what holds it there - "
                    "an assembly that is to be made has to connect it" % name,
                )
            elif index > 0 and not any(item.get(key) for key in _MANUFACTURED_CONNECTIONS):
                _report_at(
                    diagnostics,
                    root_node,
                    item_path,
                    None,
                    "'%s' says neither where it goes nor what holds it - an assembly that is to be made has to "
                    "connect it" % name,
                )
            level(item, item_path)

    if isinstance(data, dict):
        if data.get(assy_filter.LINKS) is None and "location" in data:
            # A file that is one part or one assembly and nothing else: its
            # root is not the frame of a list but the one item it places
            # ('AssemblyFactoryAssy.instantiate_async'), and 'pc test' reports
            # it like any other.
            _report_at(
                diagnostics,
                root_node,
                [],
                "location",
                "'%s' is placed by coordinates, which says where it ends up but not what holds it there - "
                "an assembly that is to be made has to connect it" % assy_filter.link_name(data, 0),
            )
        level(data, [])
    return diagnostics


def check_manufacturable_parts(data, root_node=None, inherited=None) -> list:
    """Report a part marked manufacturable that nobody could make or buy.

    A part is had in one of two ways, and the build plan asks exactly these
    two questions of it (see 'partcad.procurement'): it is made, which takes a
    'manufacturing:' section saying how, or it is bought, which takes both a
    'vendor:' and an 'sku:' -- the SKU alone does not say from whom, and the
    vendor alone does not say what. A part that is neither is one the build
    plan calls missing.

    An 'alias' or an 'enrich' is not checked: it is made of another part, and
    what it is had by is that part's. ``inherited`` is what a package above
    this one marks -- see the section comment for why only what is marked.
    """
    diagnostics: list = []
    if not isinstance(data, dict):
        return diagnostics
    package_mark = data.get("manufacturable", inherited)
    parts = data.get("parts")
    if not isinstance(parts, dict):
        return diagnostics
    for name, config in parts.items():
        if not isinstance(config, dict) or config.get("type") in _NOT_MADE_OF_ITS_OWN:
            # A bare string is the short form of an alias.
            continue
        if config.get("manufacturable", package_mark) is not True:
            continue
        if config.get("manufacturing") or (config.get("vendor") and config.get("sku")):
            continue
        _report_at(
            diagnostics,
            root_node,
            ["parts"],
            name,
            "'%s' is marked manufacturable, but says neither how it is made ('manufacturing:') nor what it "
            "is ordered by ('vendor:' and 'sku:')" % name,
        )
    return diagnostics


# ---- entry points ----------------------------------------------------------


class Render:
    """One way to render a template for checking: the values it is given, and where it includes from.

    ``variables`` are what PartCAD renders the file with -- for an ASSY file
    its parameters as ``param_<name>`` and its ``name`` (see
    'AssemblyFactoryFile.template_params'), for a ``partcad.yaml`` the names in
    'partcad_utils.config_template'. ``search_path`` is where ``{% include %}``
    looks, which for PartCAD is the directory of the file. ``label`` names what
    the values are, for a message about a rendering that failed.
    """

    def __init__(self, variables: dict, search_path=(), label: str = None):
        self.variables = dict(variables or {})
        self.search_path = list(search_path)
        self.label = label


def validate_source(
    text: str,
    schema: dict,
    renders=(),
    manufacturable: bool = False,
    inherited_manufacturable: bool = None,
) -> list:
    """Check one Jinja2-templated YAML document against ``schema``.

    Returns the diagnostics in document order. An empty list means the file is
    a valid template, renders to parsable YAML, and matches the schema.

    ``renders`` are the ways to render it (see 'Render'). The document is
    checked as each of them renders it -- the items a loop produces, the branch
    an ``{% if %}`` takes, the numbers expressions evaluate to -- and every
    finding is put back on the template line and column it came from. With
    none, the values it would be rendered with are not known (an ASSY file no
    package declares), and it is checked masked instead: see 'mask_template'.

    ``manufacturable`` says that the ASSY file is the assembly of something
    marked manufacturable, and holds it to 'check_manufacturable_assembly'.
    ``inherited_manufacturable`` is, for a ``partcad.yaml``, what a package
    above it marks its objects -- True, False, or None for nothing -- for
    'check_manufacturable_parts'.
    """
    diagnostics = check_template(text)
    if diagnostics:
        # A template that does not parse renders to nothing; masking it would
        # only invent follow-on YAML errors.
        return diagnostics

    if renders:
        for render in renders:
            diagnostics.extend(_check_rendered(text, schema, render, manufacturable, inherited_manufacturable))
    else:
        diagnostics.extend(_check_masked(text, schema, manufacturable, inherited_manufacturable))
    diagnostics.sort(key=lambda d: (d.line, d.column, d.message))
    return _dedupe(diagnostics)[:MAX_DIAGNOSTICS]


def _is_assy_schema(schema) -> bool:
    # Asked of the schema rather than of the filename, because that is what the
    # caller settled (see 'schema_for_file'), and the scene-simplified schema is
    # the same document's -- a scene's 'connect:' names a link exactly as an
    # assembly's does.
    return schema is not None and schema.get("$id") == get_schema(ASSY_SCHEMA).get("$id")


def _is_configuration_schema(schema) -> bool:
    return schema is not None and schema.get("$id") == get_schema(PARTCAD_SCHEMA).get("$id")


def _document_checks(data, schema, root_node, masked, manufacturable, inherited_manufacturable) -> list:
    """Everything said about a parsed document: its schema, and what no schema can say."""
    diagnostics = _validate_schema(data, schema, root_node, masked)
    # Only for an ASSY document, and only ever as well as the schema: a link
    # that nothing places is not a shape the schema can describe, and a
    # 'partcad.yaml' has no links at all.
    if _is_assy_schema(schema):
        diagnostics.extend(check_links(data, root_node, masked))
        if manufacturable:
            diagnostics.extend(check_manufacturable_assembly(data, root_node))
    elif _is_configuration_schema(schema):
        diagnostics.extend(check_manufacturable_parts(data, root_node, inherited_manufacturable))
    return diagnostics


def _check_rendered(text, schema, render, manufacturable, inherited_manufacturable) -> list:
    """Check ``text`` as ``render`` renders it, with every finding placed back on the template."""
    try:
        rendering = template_render.render(text, render.variables, render.search_path)
    except template_render.RenderError as exc:
        if exc.missing_template:
            # An include that is not where it is looked for. For a file checked
            # on its own that may only mean that what puts it there -- an
            # 'includePaths' declared by a package this cannot see -- is not
            # known here, so it is checked as if its values were not known.
            return _check_masked(text, schema, manufacturable, inherited_manufacturable)
        line = exc.line if exc.line is not None else 0
        values = " with the default parameters of '%s'" % render.label if render.label else ""
        return [
            Diagnostic(
                SEVERITY_ERROR,
                "Jinja2 template error while rendering it%s: %s" % (values, exc.message),
                line,
                0,
                end_line=line,
                end_column=_line_length(text, line),
                code=CODE_TEMPLATE,
            )
        ]

    try:
        data = yaml.safe_load(rendering.text)
        root_node = yaml.compose(rendering.text, Loader=yaml.SafeLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line, column = rendering.position(mark.line, mark.column) if mark is not None else (0, 0)
        return [Diagnostic(SEVERITY_ERROR, (exc.problem or str(exc)).strip(), line, column, code=CODE_YAML)]
    except Exception as exc:  # pylint: disable=broad-except
        # Not only 'yaml.YAMLError': a date that is not one ('2001-13-45') is
        # a 'ValueError' out of the parser, and nesting deep enough a
        # 'RecursionError'. Either is a finding about the file, not a crash.
        return [Diagnostic(SEVERITY_ERROR, str(exc).strip() or type(exc).__name__, 0, 0, code=CODE_YAML)]

    if data is None:
        return []
    # Nothing is masked: every value is the one PartCAD reads.
    nothing_masked = _Masked(rendering.text, [])
    found = _document_checks(data, schema, root_node, nothing_masked, manufacturable, inherited_manufacturable)
    placed = []
    for diagnostic in found:
        start, end = rendering.span((diagnostic.line, diagnostic.column), (diagnostic.end_line, diagnostic.end_column))
        placed.append(
            Diagnostic(
                diagnostic.severity,
                diagnostic.message,
                start[0],
                start[1],
                end[0],
                end[1],
                code=diagnostic.code,
                path=diagnostic.path,
            )
        )
    return placed


def _check_masked(text, schema, manufacturable, inherited_manufacturable) -> list:
    """Check ``text`` with its template masked: what is left when the values it renders with are unknown."""
    masked = mask_template(text)

    try:
        data = yaml.safe_load(masked.text)
        root_node = yaml.compose(masked.text, Loader=yaml.SafeLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line if mark is not None else 0
        column = mark.column if mark is not None else 0
        problem = (exc.problem or str(exc)).strip()
        # Masking replaces a conditional with the union of its branches, so a
        # construct such as `x: {% if c %}a{% else %}b{% endif %}` can only be
        # checked approximately. Say so instead of asserting a broken file.
        near_template = masked.overlaps((line, 0), (line + 1, 0))
        if near_template:
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    "%s (this line mixes YAML with Jinja2, so it could not be checked)" % problem,
                    line,
                    column,
                    code=CODE_YAML,
                )
            ]
        return [Diagnostic(SEVERITY_ERROR, problem, line, column, code=CODE_YAML)]
    except Exception as exc:  # pylint: disable=broad-except
        # See '_check_rendered': not every parse failure is a 'yaml.YAMLError'.
        return [Diagnostic(SEVERITY_ERROR, str(exc).strip() or type(exc).__name__, 0, 0, code=CODE_YAML)]

    if data is None:
        # An empty document (or one whose entire body is Jinja2 control flow).
        return []

    return _document_checks(data, schema, root_node, masked, manufacturable, inherited_manufacturable)


def _dedupe(diagnostics: list) -> list:
    seen = set()
    unique = []
    for diagnostic in diagnostics:
        key = (diagnostic.line, diagnostic.column, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return unique
