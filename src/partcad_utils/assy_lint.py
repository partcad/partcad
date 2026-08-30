#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Position-accurate syntax and schema checking for PartCAD's ASSY files.

Every ASSY (``*.assy``) file is a Jinja2 template that is rendered into YAML and
then has to conform to a JSON schema. That is three error classes a user can
hit -- a broken template, YAML that does not parse, and YAML that parses but
does not match the schema -- and an editor is only useful if it can point at the
*source* line of each one.

Rendering the template first is not an option here: rendering needs the
parameter values, which are only known once the whole package is loaded, and it
destroys the mapping from a rendered line back to the line the user is typing.

So this module masks the template instead. Every Jinja2 construct is replaced,
in place, with an equally sized run of inert characters:

  * ``{{ expr }}`` becomes a filler scalar, so a templated value stays a value,
  * ``{% tag %}`` and ``{# comment #}`` become blanks, so a control-flow line
    stays an empty line, and a loop or conditional body is checked once.

Newlines inside a construct are preserved, so the masked document has exactly
the same line and column layout as the file on disk: a YAML parse error, or a
schema violation resolved through the composed YAML node tree, lands on the
character the user actually wrote.

Masking necessarily loses information -- what a ``{{ expr }}`` evaluates to, and
which branch of a ``{% if %}`` is taken -- so any finding that depends on that
lost information is dropped rather than reported. That trades a missed error for
never underlining correct code, which is the right trade for an editor.

It lives here, next to ``framing`` and ``workspace``, because neither end owns
it. The daemon checks a package's ASSY files when `pc lint` walks the package
graph; every client checks the one file somebody is editing, in its own process
(`partcad_client.lint`). Both are answering the same question about the same
documents, so a copy on each side is a copy that can disagree -- and a
disagreement here means the editor and CI contradicting each other about a file.
Nothing in this module needs a loaded PartCAD context, or ``partcad`` at all.
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

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# Source of every diagnostic produced here, so editors can group them.
SOURCE = "partcad"

# Diagnostic codes, reported alongside the message.
CODE_TEMPLATE = "jinja2"
CODE_YAML = "yaml"
CODE_SCHEMA = "schema"

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

# File extensions whose content this module knows how to check. `partcad.yaml`
# is deliberately absent: it is checked by `partcad.lint.schema.SchemaLinting`,
# which reports per-package rather than per-position, and turning its schema
# loose on an editor would surface every gap in it as a squiggle on a working
# file.
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
    return _SCHEMA_BY_EXTENSION.get(os.path.splitext(os.path.basename(path))[1].lower())


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
    """The schema that governs ``path`` when read as ``flavor``, or None."""
    name = schema_name_for_file(path)
    if name is None:
        return None
    if flavor != FLAVOR_SCENE:
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
        out.append(text[index:at])
        out.append(_blank_like(text[at:end], kind))
        spans.append((_to_position(line_starts, at), _to_position(line_starts, end), kind))
        index = end
    return _Masked("".join(out), spans)


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
    """Descend into a failed anyOf/oneOf for the most informative sub-error."""
    while error.context:
        better = jsonschema.exceptions.best_match(error.context)
        if better is None or better is error:
            break
        error = better
    return error


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
        if error.validator in _VALUE_VALIDATORS and masked.overlaps(start, end, _EXPR):
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


def _fallback_span(node):
    if node is None:
        return ((0, 0), (0, 1))
    return _node_span(node)


# ---- entry points ----------------------------------------------------------


def validate_source(text: str, schema: dict) -> list:
    """Check one Jinja2-templated YAML document against ``schema``.

    Returns the diagnostics in document order. An empty list means the file is
    a valid template, renders to parsable YAML on every branch this can see, and
    matches the schema.
    """
    diagnostics = check_template(text)
    if diagnostics:
        # A template that does not parse renders to nothing; masking it would
        # only invent follow-on YAML errors.
        return diagnostics

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
    except yaml.YAMLError as exc:
        return [Diagnostic(SEVERITY_ERROR, str(exc).strip(), 0, 0, code=CODE_YAML)]

    if data is None:
        # An empty document (or one whose entire body is Jinja2 control flow).
        return []

    diagnostics = _validate_schema(data, schema, root_node, masked)
    diagnostics.sort(key=lambda d: (d.line, d.column, d.message))
    return _dedupe(diagnostics)[:MAX_DIAGNOSTICS]


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
