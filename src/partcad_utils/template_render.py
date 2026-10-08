#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Rendering a Jinja2 template while remembering where each rendered character came from.

An ASSY file and a `partcad.yaml` are Jinja2 templates, and what PartCAD reads
is what they render to: the items a loop produces, the branch an `{% if %}`
takes, the number an expression evaluates to. Checking the template rather than
its rendering -- masking every tag and reading what is left -- misses all of
that. Checking the rendering instead has one problem, and this module is the
answer to it: a finding in rendered text is no use to somebody editing the
template unless it points at the line and column they wrote.

So the template is rendered with markers in its output. Before it is compiled,
every piece of literal text and every `{{ expr }}` that reaches the document is
preceded by a marker naming the source line and column it came from; after
rendering, the markers are stripped and kept as anchors. A rendered position
then maps back to its anchor: a character of literal text to the very same
character in the source, a character an expression produced to that `{{ }}`.

What is not marked:

  * the body of a `{% macro %}`, a `{% call %}`, a `{% filter %}` and a block
    `{% set %}`. Their output becomes a *value* -- a macro's result, a caller's
    text, a variable -- which the template may compare, measure or transform,
    and a marker in it would change the answer. Their text is attributed to
    where it reaches the document instead: a macro's lines to the `{{ m() }}`
    that called it, a block `set` to the `{{ var }}` that printed it.
  * what an `{% include %}` brings in, which is attributed to the include.

The rendering is done with Jinja2's sandbox, as PartCAD renders an ASSY file:
the file being checked may be somebody else's, and the check runs on whoever has
it open.
"""

import bisect
import os
import re
import time
import traceback

import jinja2
import jinja2.meta
from jinja2 import nodes
from jinja2.sandbox import SandboxedEnvironment, SecurityError

# Private-use characters: nothing a YAML document or a template is going to
# contain on purpose, and they are gone before anything else sees the text.
_OPEN = ""
_CLOSE = ""
_MARKER = re.compile(_OPEN + r"([de]):(\d+):(\d+):(\d+)" + _CLOSE)

# What an anchor stands for. Literal text maps character for character; an
# expression's output, however long, maps to the whole of its `{{ }}`.
_DATA = "d"
_EXPR = "e"

# Statements whose body reaches the document as a value rather than in place.
_DETACHED = (nodes.Macro, nodes.CallBlock, nodes.FilterBlock, nodes.AssignBlock)
# Statements that put text in the document where they stand, by the tag name
# their construct starts with.
_EMITTING = {nodes.Include: "include", nodes.CallBlock: "call", nodes.FilterBlock: "filter"}

_CONSTRUCTS = (("{{", "}}"), ("{%", "%}"), ("{#", "#}"))

# What one rendering may cost. It runs when a file is opened and on every
# keystroke after that, on templates from whatever package is open -- and from
# up to eight 'partcad.yaml' files above it -- so a template that would take a
# minute or a gigabyte is stopped and reported rather than waited for. The
# sandbox already caps 'range()'; these are what it does not cap.
MAX_OUTPUT = 4 * 1024 * 1024
MAX_SECONDS = 5.0
MAX_SEQUENCE = 1024 * 1024
MAX_POWER_BITS = 1024 * 1024


class _BoundedSandbox(SandboxedEnvironment):
    """Jinja2's sandbox, with the two operators that can make a value of any size checked first."""

    intercepted_binops = frozenset(["*", "**"])

    def call_binop(self, context, operator, left, right):
        if operator == "*":
            for sequence, count in ((left, right), (right, left)):
                if (
                    isinstance(sequence, (str, list, tuple))
                    and isinstance(count, int)
                    and len(sequence) * count > MAX_SEQUENCE
                ):
                    raise SecurityError("a value repeated %d times is longer than a template may make" % count)
        elif operator == "**":
            if (
                isinstance(left, int)
                and isinstance(right, int)
                and right > 0
                and abs(left) > 1
                and left.bit_length() * right > MAX_POWER_BITS
            ):
                raise SecurityError("%d ** %d is larger than a template may make" % (left, right))
        return super().call_binop(context, operator, left, right)


def _environment(search_path) -> _BoundedSandbox:
    return _BoundedSandbox(loader=jinja2.FileSystemLoader([str(path) for path in search_path]))


def _generate(template, variables) -> str:
    """Render ``template`` within the budget above."""
    started = time.monotonic()
    size = 0
    chunks = []
    for chunk in template.generate(variables):
        size += len(chunk)
        chunks.append(chunk)
        if size > MAX_OUTPUT:
            raise RenderError("it renders to more than %d characters" % MAX_OUTPUT)
        if time.monotonic() - started > MAX_SECONDS:
            raise RenderError("it takes more than %d seconds to render" % MAX_SECONDS)
    return "".join(chunks)


class RenderError(Exception):
    """Rendering raised. ``line`` is the zero-based source line it raised on, if known."""

    def __init__(self, message: str, line: int = None, missing_template: bool = False):
        super().__init__(message)
        self.message = message
        self.line = line
        # It includes or imports a file that is not where it is looked for --
        # which, for a file checked on its own, may only mean that what puts it
        # there (an 'includePaths' somebody else declares) is not known here.
        self.missing_template = missing_template


class Rendering:
    """A rendered document, and the way back from any position in it to the source."""

    def __init__(self, text: str, anchors: list, source: str):
        self.text = text
        self._anchors = anchors
        self._offsets = [anchor[0] for anchor in anchors]
        self._line_starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
        self._source_lines = source.split("\n")

    def _offset(self, line: int, column: int) -> int:
        line = min(max(line, 0), len(self._line_starts) - 1)
        return min(self._line_starts[line] + max(column, 0), len(self.text))

    def _anchor(self, offset: int):
        index = bisect.bisect_right(self._offsets, offset) - 1
        return self._anchors[index] if index >= 0 else None

    def _line_length(self, line: int) -> int:
        if 0 <= line < len(self._source_lines):
            return len(self._source_lines[line].rstrip("\r"))
        return 0

    def position(self, line: int, column: int) -> tuple:
        """The source (line, column) the rendered character at (line, column) came from."""
        offset = self._offset(line, column)
        anchor = self._anchor(offset)
        if anchor is None:
            return (0, 0)
        anchor_offset, kind, source_line, source_column, _ = anchor
        if kind == _DATA:
            return (source_line, min(source_column + offset - anchor_offset, self._line_length(source_line)))
        return (source_line, source_column)

    def span(self, start: tuple, end: tuple) -> tuple:
        """The source span a rendered span [start, end) came from, as two (line, column) pairs."""
        source_start = self.position(*start)
        end_offset = self._offset(*end)
        start_offset = self._offset(*start)
        if end_offset <= start_offset:
            return source_start, (source_start[0], source_start[1] + 1)
        # The last character inside the span decides where it ends: the end
        # itself is the first character after it, which may belong to the next
        # piece of the template.
        anchor = self._anchor(end_offset - 1)
        if anchor is None:
            return source_start, (source_start[0], source_start[1] + 1)
        anchor_offset, kind, source_line, source_column, source_end = anchor
        if kind == _DATA:
            source_finish = (
                source_line,
                min(source_column + end_offset - anchor_offset, self._line_length(source_line)),
            )
        else:
            source_finish = (source_line, source_end)
        if source_finish <= source_start:
            # A span whose end comes from earlier in the source than its start
            # (a loop's second pass, a macro): underline the rest of the line.
            source_finish = (source_start[0], max(self._line_length(source_start[0]), source_start[1] + 1))
        return source_start, source_finish


def render(source: str, variables: dict, search_path=()) -> Rendering:
    """Render ``source`` with ``variables``, keeping the way back to it.

    ``search_path`` is where `{% include %}` and `{% import %}` look, as the
    directory of the file being rendered is for PartCAD. Raises `RenderError`
    when the template does not parse, raises while rendering, or goes over the
    budget above.
    """
    environment = _environment(search_path)
    try:
        tree = environment.parse(source)
    except jinja2.TemplateSyntaxError as exc:
        raise RenderError(exc.message or str(exc), (exc.lineno or 1) - 1) from exc
    _Instrumenter(source).statements(tree.body)
    try:
        marked = _generate(environment.from_string(tree), variables)
    except RenderError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise RenderError(_describe(exc), _template_line(exc), isinstance(exc, jinja2.TemplateNotFound)) from exc
    return _strip(marked, source)


def render_plain(source: str, variables: dict, search_path=()) -> str:
    """Render ``source`` within the same sandbox and budget, without keeping the way back."""
    environment = _environment(search_path)
    try:
        return _generate(environment.from_string(source), variables)
    except RenderError:
        raise
    except jinja2.TemplateSyntaxError as exc:
        raise RenderError(exc.message or str(exc), (exc.lineno or 1) - 1) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise RenderError(_describe(exc), _template_line(exc), isinstance(exc, jinja2.TemplateNotFound)) from exc


def referenced_files(source: str, search_path=()) -> tuple:
    """Every file ``source`` includes or imports, transitively; and whether it names one by an expression.

    For a cache that has to know when what a template reads has changed: the
    files that are found by their paths, the ones that are not by their names
    (so that creating one changes the answer), and True where a name is only
    known once the template runs, which no list made in advance can cover.
    """
    environment = _environment(search_path)
    found = []
    missing = []
    dynamic = False
    seen = set()
    pending = [source]
    while pending:
        text = pending.pop()
        try:
            names = list(jinja2.meta.find_referenced_templates(environment.parse(text)))
        except Exception:  # pylint: disable=broad-except
            continue
        for name in names:
            if name is None:
                dynamic = True
                continue
            if name in seen:
                continue
            seen.add(name)
            try:
                included, filename, _ = environment.loader.get_source(environment, name)
            except Exception:  # pylint: disable=broad-except
                missing.append(name)
                continue
            found.append(os.path.abspath(filename))
            pending.append(included)
    return sorted(found), sorted(missing), dynamic


def _describe(exc: Exception) -> str:
    if isinstance(exc, jinja2.TemplateError):
        return str(exc.message if getattr(exc, "message", None) else exc)
    return "%s: %s" % (type(exc).__name__, exc)


def _template_line(exc: Exception):
    """The source line a rendering error was raised on, from the traceback Jinja2 rewrites."""
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if frame.filename == "<template>" and frame.lineno:
            return frame.lineno - 1
    lineno = getattr(exc, "lineno", None)
    return lineno - 1 if lineno else None


def _strip(marked: str, source: str) -> Rendering:
    """Take the markers out of ``marked``, keeping each as an anchor at its rendered offset."""
    pieces = []
    anchors = []
    length = 0
    position = 0
    for match in _MARKER.finditer(marked):
        piece = marked[position : match.start()]
        pieces.append(piece)
        length += len(piece)
        kind, line, column, end = match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4))
        anchors.append((length, kind, line, column, end))
        position = match.end()
    pieces.append(marked[position:])
    return Rendering("".join(pieces), anchors, source)


def _constructs(source: str) -> list:
    """Every `{{ }}`, `{% %}` and `{# #}` in ``source``, as (start, end, opening) offsets."""
    found = []
    index = 0
    while True:
        best = None
        for opening, closing in _CONSTRUCTS:
            at = source.find(opening, index)
            if at != -1 and (best is None or at < best[0]):
                best = (at, opening, closing)
        if best is None:
            return found
        at, opening, closing = best
        end = source.find(closing, at + 2)
        end = len(source) if end == -1 else end + 2
        found.append((at, end, opening))
        index = end


class _Instrumenter:
    """Puts a marker in front of everything a template writes into the document.

    Positions are worked out against the source as the tree is walked, which is
    in source order: each line keeps a cursor past what has been placed on it,
    and a piece of text is looked for only outside the template's own tags, so
    the `x` in `{% for x in xs %}x` is found where it is written.
    """

    def __init__(self, source: str):
        self.source = source
        self.line_starts = [0] + [index + 1 for index, char in enumerate(source) if char == "\n"]
        self.lines = source.split("\n")
        self.constructs = _constructs(source)
        self.construct_starts = [start for start, _, _ in self.constructs]
        self.cursor = {}
        # The constructs a marker has been placed for. Each is one expression
        # or one statement, and the tree is walked in source order, so the
        # next one of the right kind that is not taken yet is the one.
        self.used = set()

    # -- walking -------------------------------------------------------------

    def statements(self, body: list) -> None:
        index = 0
        while index < len(body):
            statement = body[index]
            if isinstance(statement, nodes.Output):
                statement.nodes = self.output(statement.nodes)
            elif isinstance(statement, tuple(_EMITTING)):
                line, start, end = self.next_construct(statement.lineno - 1, "{%", _EMITTING[type(statement)])
                body.insert(index, nodes.Output([self.marker(_EXPR, line, start, end, statement.lineno)]))
                index += 1
            if not isinstance(statement, _DETACHED):
                for field in ("body", "elif_", "else_"):
                    value = getattr(statement, field, None)
                    if isinstance(value, list):
                        self.statements(value)
            index += 1

    def output(self, children: list) -> list:
        marked = []
        for child in children:
            if isinstance(child, nodes.TemplateData):
                marked.append(nodes.TemplateData(self.data(child.data, child.lineno - 1), lineno=child.lineno))
            else:
                line, start, end = self.next_construct(child.lineno - 1, "{{")
                marked.append(self.marker(_EXPR, line, start, end, child.lineno))
                marked.append(child)
        return marked

    # -- placing -------------------------------------------------------------

    @staticmethod
    def marker(kind, line, column, end, lineno) -> nodes.TemplateData:
        return nodes.TemplateData("%s%s:%d:%d:%d%s" % (_OPEN, kind, line, column, end, _CLOSE), lineno=lineno)

    def data(self, text: str, line: int) -> str:
        pieces = text.split("\n")
        marked = []
        for index, piece in enumerate(pieces):
            if index == 0:
                column = self.locate(line, piece, ends_line=len(pieces) > 1)
            else:
                # After a newline in literal text: the start of the next line.
                column = 0
                self.cursor[line + index] = len(piece)
            marked.append("%s%s:%d:%d:%d%s%s" % (_OPEN, _DATA, line + index, column, column, _CLOSE, piece))
        return "\n".join(marked)

    def locate(self, line: int, piece: str, ends_line: bool) -> int:
        """Where on ``line`` a piece of literal text starts, outside the template's tags."""
        if not 0 <= line < len(self.lines):
            return 0
        text = self.lines[line]
        cursor = self.cursor.get(line, 0)
        if ends_line and piece and text.endswith(piece) and not self.inside(line, len(text) - len(piece)):
            column = len(text) - len(piece)
        else:
            column = cursor
            if piece:
                at = text.find(piece, cursor)
                while at != -1 and self.inside(line, at):
                    at = text.find(piece, at + 1)
                if at != -1:
                    column = at
        self.cursor[line] = column + len(piece)
        return column

    def next_construct(self, line: int, opening: str, keyword: str = None) -> tuple:
        """Where the construct a node on ``line`` was written in is, as (line, column, end column).

        The first construct not taken yet that opens with ``opening`` (and, for
        a statement, names ``keyword``) and reaches ``line``: one that starts on
        it at or after its cursor, or one that started on an earlier line and
        runs onto it -- Jinja2 numbers an expression by its first token, which
        is not always on the line of its ``{{``. The line returned is the one it
        starts on, which is where it is written.
        """
        if not 0 <= line < len(self.lines):
            return (max(line, 0), 0, 1)
        line_start = self.line_starts[line]
        line_end = line_start + len(self.lines[line])
        cursor = line_start + self.cursor.get(line, 0)
        # Everything that could reach this line starts before its end, so the
        # search runs back from there.
        index = bisect.bisect_right(self.construct_starts, line_end)
        candidates = []
        while index > 0:
            index -= 1
            start, end, kind = self.constructs[index]
            if end <= line_start:
                break
            on_line = start >= line_start
            if kind != opening or index in self.used or (on_line and start < cursor):
                continue
            if keyword is not None and not re.match(r"[-+]?\s*%s\b" % keyword, self.source[start + 2 : end]):
                continue
            candidates.append(index)
        if not candidates:
            column = self.cursor.get(line, 0)
            return (line, column, max(column + 1, len(self.lines[line])))
        index = min(candidates)
        self.used.add(index)
        start, end, _ = self.constructs[index]
        start_line = bisect.bisect_right(self.line_starts, start) - 1
        end_line = bisect.bisect_right(self.line_starts, max(end - 1, start)) - 1
        end_column = end - self.line_starts[end_line]
        self.cursor[end_line] = max(self.cursor.get(end_line, 0), end_column)
        start_column = start - self.line_starts[start_line]
        if end_line != start_line:
            end_column = len(self.lines[start_line])
        return (start_line, start_column, end_column)

    def inside(self, line: int, column: int) -> bool:
        offset = self.line_starts[line] + column
        index = bisect.bisect_right(self.construct_starts, offset) - 1
        return index >= 0 and offset < self.constructs[index][1]
