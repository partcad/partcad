#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a comment on a part or a sketch may point at besides 'face:12': a selection, as a script would make it.

A comment's ``ref`` says what inside the object it is about (see
``partcad_utils.comments``). For a part or a sketch that can be one face or edge
by its number -- ``face:12`` -- or a *selection*, written the way the script that
makes the part would select it:

* a CadQuery selection: a chain of ``Workplane`` calls, each with a string
  selector, as ``faces(">Z")``, ``edges("|Z and >X")`` or
  ``faces("%PLANE").faces(">Z[-2]")`` (and ``first()``, ``last()``, ``item(n)``);
* a build123d selection: ``faces()``, ``edges()``... and the ``ShapeList``
  methods after it, as ``faces().sort_by(Axis.Z)[-1]`` or
  ``edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[0]``.

The two are told apart by the call they start with: a CadQuery selection hands
the first one a selector, and a build123d one hands it nothing. A selection is
worked out where the shape is, in a sandbox, by evaluating it with ``eval()``
against the shape (``element_refs`` among the wrappers) -- which is why what may
be written is held to a grammar first (:func:`problem`): a chain of the calls
above, with constants, ``Axis``, ``GeomType``, ``SortBy``, ``Plane`` and
``Vector`` for arguments, and nothing else, no name beginning with an
underscore. A selection is about every face or edge it selects, and its callout
is pinned to one of them.

Stdlib only. ``src/partcad/wrappers/selector_refs.py`` is a byte-identical copy
for the sandbox, which cannot import this package, and a test fails if the two
differ: edit this one and copy it over.
"""

import ast
import typing

CADQUERY = "cadquery"
BUILD123D = "build123d"

# What a selection starts with: the kind of thing selected.
KINDS = ("faces", "edges", "vertices", "wires", "solids", "shells")

# What a CadQuery chain may call besides a selection, and how many integers each takes.
CADQUERY_PICKS = {"first": 0, "last": 0, "item": 1}

# What a build123d chain may call, or read, after its first call.
BUILD123D_METHODS = frozenset(
    KINDS
    + (
        "sort_by",
        "group_by",
        "filter_by",
        "filter_by_position",
        "sort_by_distance",
        "face",
        "edge",
        "vertex",
        "wire",
        "solid",
        "shell",
        "first",
        "last",
    )
)

# The names a build123d selection's arguments may use: the enumerations and the
# geometry ShapeList methods take.
BUILD123D_NAMES = ("Axis", "GeomType", "SortBy", "Plane", "Vector")

# What a selection may be no longer than, in characters.
MAX_LENGTH = 1000


def _number(node) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) in (int, float)


def _integer(node) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        node = node.operand
    return isinstance(node, ast.Constant) and type(node.value) is int


def _argument(node) -> typing.Optional[str]:
    """Why ``node`` is not an argument a build123d selection may hand a method, or None."""
    if _number(node) or (isinstance(node, ast.Constant) and type(node.value) in (bool, str, type(None))):
        return None
    if isinstance(node, ast.Tuple):
        for item in node.elts:
            found = _argument(item)
            if found:
                return found
        return None
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id not in BUILD123D_NAMES:
            return "only %s may be named in an argument" % ", ".join(BUILD123D_NAMES)
        if node.attr.startswith("_"):
            return "'%s' begins with an underscore" % node.attr
        return None
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in BUILD123D_NAMES:
            return "only %s may be made in an argument" % ", ".join(BUILD123D_NAMES)
        for item in list(node.args) + [keyword.value for keyword in node.keywords]:
            found = _argument(item)
            if found:
                return found
        if any(keyword.arg is None or keyword.arg.startswith("_") for keyword in node.keywords):
            return "a keyword argument is named, and does not begin with an underscore"
        return None
    return "an argument is a number, a string, a tuple, or one of %s" % ", ".join(BUILD123D_NAMES)


def _links(node) -> typing.List[ast.AST]:
    """The chain, first call first: each a Call, a Subscript or an Attribute over the one before it."""
    links = []
    while isinstance(node, (ast.Call, ast.Subscript, ast.Attribute)):
        links.append(node)
        if isinstance(node, ast.Call):
            node = node.func.value if isinstance(node.func, ast.Attribute) else None
        else:
            node = node.value
        if node is None:
            break
    links.reverse()
    return links


def classify(ref) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
    """``(style, problem)`` of ``ref``: CADQUERY or BUILD123D and None, or None and why it is no selection.

    A string that does not even start like one -- ``face:12``, a link name --
    is ``(None, None)``: not a selection, and nothing wrong with it as a ref.
    """
    if not isinstance(ref, str):
        return None, None
    text = ref.strip()
    # Written as a selection: one of the kinds, called. Anything else -- a
    # link name, 'face:12' -- is some other kind of ref.
    if not any(text.startswith(name) and text[len(name) :].lstrip().startswith("(") for name in KINDS):
        return None, None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None, "it is not an expression Python reads"
    links = _links(tree.body)
    first = links[0] if links else None
    if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id in KINDS):
        return None, "it is not one chain of calls starting with %s" % ", ".join(KINDS)
    if len(text) > MAX_LENGTH:
        return None, "it is longer than %d characters" % MAX_LENGTH
    if first.keywords:
        return None, "'%s' takes no keyword argument" % first.func.id
    if len(first.args) == 1 and isinstance(first.args[0], ast.Constant) and isinstance(first.args[0].value, str):
        return _cadquery(links)
    if not first.args:
        return _build123d(links)
    return None, "'%s(...)' takes one string selector (CadQuery) or nothing (build123d)" % first.func.id


def _cadquery(links) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
    for link in links[1:]:
        if not isinstance(link, ast.Call) or not isinstance(link.func, ast.Attribute):
            return None, "a CadQuery selection is a chain of calls"
        name = link.func.attr
        if link.keywords:
            return None, "'%s' is called with no keyword argument" % name
        if name in KINDS:
            if not (
                len(link.args) == 1 and isinstance(link.args[0], ast.Constant) and isinstance(link.args[0].value, str)
            ):
                return None, "'%s' is called with one string selector" % name
        elif name in CADQUERY_PICKS:
            if len(link.args) != CADQUERY_PICKS[name] or not all(_integer(arg) for arg in link.args):
                return None, "'%s' is called with %d integer(s)" % (name, CADQUERY_PICKS[name])
        else:
            return None, "'%s' is not a CadQuery selection (%s)" % (name, ", ".join(KINDS + tuple(CADQUERY_PICKS)))
    return CADQUERY, None


def _build123d(links) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
    for link in links[1:]:
        if isinstance(link, ast.Subscript):
            index = link.slice
            if isinstance(index, ast.Slice):
                if not all(part is None or _integer(part) for part in (index.lower, index.upper, index.step)):
                    return None, "a slice is of integers"
            elif not _integer(index):
                return None, "an index is an integer"
            continue
        name = link.func.attr if isinstance(link, ast.Call) else link.attr
        if not isinstance(link, ast.Call) or not isinstance(link.func, ast.Attribute):
            if isinstance(link, ast.Attribute) and name in ("first", "last"):
                continue
            return None, "a build123d selection is a chain of ShapeList methods"
        if name.startswith("_") or name not in BUILD123D_METHODS:
            return None, "'%s' is not a ShapeList method a selection may call (%s)" % (
                name,
                ", ".join(sorted(BUILD123D_METHODS)),
            )
        for argument in list(link.args) + [keyword.value for keyword in link.keywords]:
            found = _argument(argument)
            if found:
                return None, found
        if any(keyword.arg is None or keyword.arg.startswith("_") for keyword in link.keywords):
            return None, "a keyword argument is named, and does not begin with an underscore"
    return BUILD123D, None


def style(ref) -> typing.Optional[str]:
    """CADQUERY or BUILD123D for a selection that may be evaluated, else None."""
    found, problem = classify(ref)
    return None if problem else found


def problem(ref) -> typing.Optional[str]:
    """Why ``ref``, written as a selection, is not one that may be evaluated; None for a good one or for no selection."""
    return classify(ref)[1]


def kind(ref) -> typing.Optional[str]:
    """What a selection selects first -- 'faces', 'edges', ... -- or None for no selection."""
    if style(ref) is None:
        return None
    return ref.strip().split("(", 1)[0]
