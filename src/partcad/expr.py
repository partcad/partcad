#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's own expression syntax, ``%<expression>%``.

Jinja2 owns ``{{ ... }}`` and ``{% ... %}`` in ``partcad.yaml``: the file is
rendered as a template *before* it is parsed (see 'ProjectLocal'), so anything
written that way is resolved at load time, where the parameter values of an
individual object do not exist yet. An expression that has to wait for those
values therefore cannot be spelled in Jinja2's syntax at all - it would be
evaluated, and fail, one step too early.

``%...%`` is what is left. The delimiters are not new here: the names in an
interface's ``inherits:`` section have been resolved this way since interfaces
were introduced, in the one form ``%name:expression%``. This module is that
mechanism generalized - the same delimiters, applied to any string in a
declaration and over all of the object's parameters rather than one named one -
and the historical form still means what it meant.

Three forms, tried in this order:

* ``%name%`` - the value of the parameter called ``name``, with its own type.
  A location entry written ``"%depth%"`` stays the number it was declared as.
  New: the historical resolver required the colon below and raised without it.
* ``%name:expression%`` - the historical form, where ``name`` is a parameter and
  ``value`` is bound to its value inside ``expression``.
* ``%expression%`` - arithmetic over the object's parameters, e.g. ``%size / 2%``
  or ``%-width / 2 + offset%``.

What an expression may do is checked rather than assumed ('_ALLOWED_NODES',
'SAFE_ATTRIBUTES'), because a declaration is read whenever a package is loaded,
long before anything is built and any CAD script runs. Arithmetic, comparisons,
a conditional, indexing, and the plain methods of a string or a number: enough
for ``value[1:value.index('-')]``, which is what the historical form is used
for, and not enough to reach an object's insides.

A string that is *exactly* one expression evaluates to the value itself, so a
number stays a number. A string that merely contains one (``"m;size=%size%"``,
``"%depth%mm deep"``) gets the value formatted into it.
"""

import ast
import bisect
import math
import re
from typing import Any

from . import logging as pc_logging
from .consts import CAD_CONSTANTS

# Deliberately '[^%]' rather than '[^%*]': the historical pattern in
# 'Interface.instantiate' excluded '*' as well, which quietly made '%a*b%'
# not an expression. There is no reason a product cannot be one.
PATTERN = re.compile(r"%([^%]+)%")


def _is_number(value: Any) -> bool:
    # A flag is an int to Python and not a quantity to anybody writing one.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: Any, what: str) -> float:
    if not _is_number(value):
        raise TypeError("%s is %r, not a number" % (what, value))
    return value


def _sequence(value: Any, what: str) -> list:
    if not isinstance(value, (list, tuple)):
        raise TypeError("%s is %r, not a list" % (what, value))
    return list(value)


def _stops(x: Any, xs: Any, ys: Any, what: str) -> tuple:
    """'(x, xs, ys)' of an interpolation, checked: the stops strictly increasing, as many values as stops."""
    x = _number(x, "the position")
    xs = _sequence(xs, "the stops")
    ys = _sequence(ys, "the %s" % what)
    if len(xs) < 2:
        raise ValueError("an interpolation needs at least 2 stops, and has %d" % len(xs))
    if len(xs) != len(ys):
        raise ValueError("there are %d stops and %d %s: one for each" % (len(xs), len(ys), what))
    for index, stop in enumerate(xs):
        _number(stop, "the stop %d" % index)
    for index in range(1, len(xs)):
        if not xs[index] > xs[index - 1]:
            raise ValueError(
                "the stops increase strictly, and %r is not above the %r before it" % (xs[index], xs[index - 1])
            )
    return x, xs, ys


def _segment(x: float, xs: list) -> tuple:
    """'(index, fraction)': x is the fraction of the way from xs[index] to xs[index + 1], 0 at a stop itself.

    Asked only for an x inside the stops. A stop starts the segment after it,
    so that the value at a stop is the one written for it, to the digit.
    """
    index = bisect.bisect_right(xs, x) - 1
    index = min(max(index, 0), len(xs) - 2)
    return index, (x - xs[index]) / (xs[index + 1] - xs[index])


def clamp(x, lo, hi):
    """'x', bounded to [lo, hi]."""
    x, lo, hi = _number(x, "the value"), _number(lo, "the lower bound"), _number(hi, "the upper bound")
    if lo > hi:
        raise ValueError("the lower bound %r is above the upper bound %r" % (lo, hi))
    return min(max(x, lo), hi)


def lerp(a, b, t):
    """'a + (b - a) * t': 'a' at t = 0, 'b' at t = 1, and the same line beyond them (t is not clamped)."""
    a, b, t = _number(a, "the start"), _number(b, "the end"), _number(t, "the fraction")
    return a + (b - a) * t


def interpolate(x, xs, ys):
    """The piecewise-linear function through the points (xs[i], ys[i]), at 'x'.

    Constant past the ends - ys[0] below xs[0], ys[-1] above xs[-1] - rather
    than extrapolated: a value outside the points somebody measured is a
    claim, and one a declaration makes by writing the line itself.
    """
    x, xs, ys = _stops(x, xs, ys, "values")
    for index, value in enumerate(ys):
        _number(value, "the value %d" % index)
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    index, t = _segment(x, xs)
    if t == 0:
        return ys[index]
    return ys[index] + (ys[index + 1] - ys[index]) * t


def pick(key, keys, values):
    """'values[keys.index(key)]': the lookup in a table an expression has no other way to write."""
    keys = _sequence(keys, "the keys")
    values = _sequence(values, "the values")
    if len(keys) != len(values):
        raise ValueError("there are %d keys and %d values: one for each" % (len(keys), len(values)))
    if key not in keys:
        raise ValueError("%r is not one of the keys %s" % (key, ", ".join(repr(each) for each in keys)))
    return values[keys.index(key)]


def _css_color():
    # The wrappers directory holds the CSS reader, which a sandbox imports too
    # (see 'partcad.cmf'); put on the path here so that this module needs
    # nothing imported before it.
    import os
    import sys

    wrappers = os.path.join(os.path.dirname(__file__), "wrappers")
    if wrappers not in sys.path:
        sys.path.append(wrappers)
    import css_color

    return css_color


def _colour(value: Any, what: str):
    parsed = _css_color().parse(value) if isinstance(value, str) else None
    if parsed is None:
        raise ValueError("%s is %r, which is not a CSS colour" % (what, value))
    return parsed


def color_mix(c0, c1, t):
    """Two CSS colours mixed as CSS's 'color-mix(in oklab, c0, c1 t)' mixes them, as '#RRGGBB' or '#RRGGBBAA'.

    't' is the share of 'c1', clamped to [0, 1]: 0 is 'c0', 1 is 'c1'.
    """
    css_color = _css_color()
    first, second = _colour(c0, "the first colour"), _colour(c1, "the second colour")
    return css_color.to_hex(css_color.mix_oklab(first, second, _number(t, "the share")))


def interpolate_color(x, xs, colors):
    """'interpolate' for colours: the stops' colours mixed in Oklab, the first and last colour past the ends."""
    x, xs, colors = _stops(x, xs, colors, "colours")
    css_color = _css_color()
    parsed = [_colour(each, "the colour %d" % index) for index, each in enumerate(colors)]
    if x <= xs[0]:
        return css_color.to_hex(parsed[0])
    if x >= xs[-1]:
        return css_color.to_hex(parsed[-1])
    index, t = _segment(x, xs)
    return css_color.to_hex(css_color.mix_oklab(parsed[index], parsed[index + 1], t))


# What an expression may call. '__builtins__' is emptied - an expression in a
# package declaration is not a place to open files from - and what is put back
# is the arithmetic that writing a coordinate actually needs.
SAFE_NAMES: dict[str, Any] = {
    "abs": abs,
    "bool": bool,
    "float": float,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "str": str,
    "acos": math.acos,
    "asin": math.asin,
    "atan": math.atan,
    "atan2": math.atan2,
    "ceil": math.ceil,
    "cos": math.cos,
    "degrees": math.degrees,
    "floor": math.floor,
    "hypot": math.hypot,
    "log": math.log,
    "pow": math.pow,
    "radians": math.radians,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tan": math.tan,
    # What a value is worked out from a table with: a parametric material's
    # density across its grades, a colour across a range of compositions. The
    # tables are lists an expression writes ('[15, 45]'); see the functions.
    "clamp": clamp,
    "lerp": lerp,
    "interpolate": interpolate,
    "pick": pick,
    "color_mix": color_mix,
    "interpolate_color": interpolate_color,
    # The same constants the template 'partcad.yaml' is rendered from has.
    **CAD_CONSTANTS,
}


class ExpressionError(Exception):
    """An expression that could not be evaluated, with the text that failed."""

    def __init__(self, expression: str, cause: Exception):
        self.expression = expression
        self.cause = cause
        super().__init__("failed to evaluate '%%%s%%': %s" % (expression, cause))


def evaluate(expression: str, values: dict[str, Any]) -> Any:
    """The value of one ``%...%`` expression, given the object's parameters."""
    name = expression.strip()
    if name in values:
        # The whole expression is a parameter name: hand the value back as it
        # is, so that a number stays a number and a string stays a string.
        return values[name]

    if ":" in expression:
        # The historical '%name:expression%', where 'value' is the parameter.
        head, _, tail = expression.partition(":")
        head = head.strip()
        if head in values:
            return _eval(tail, {**values, "value": values[head]}, expression)

    return _eval(expression, values, expression)


# What an expression may be made of. Arithmetic, comparisons, a conditional and
# a call to one of the names above - and nothing that reaches for an object's
# insides.
#
# The check is on the syntax tree rather than on the names in scope, because
# emptying '__builtins__' is not by itself a sandbox: '().__class__' walks from
# any literal to every class in the interpreter, so an expression that may write
# an attribute access may do anything at all. A declaration in 'partcad.yaml' is
# read whenever a package is loaded - long before anything is built and any CAD
# script runs - so what it is allowed to do is worth stating rather than
# assuming.
_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Compare,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Tuple,
    ast.List,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.boolop,
    # The arithmetic, named one by one rather than as 'ast.operator'. What that
    # leaves out is the point: '**' is how a short expression becomes an
    # expensive one, and '%9**9**9%' does not finish. A declaration is evaluated
    # while a package is *loaded*, in this process, before anything is sandboxed
    # - so a package fetched from a git URL could hang the PartCAD that imported
    # it. 'pow()' is still available and cannot: it is 'math.pow', which answers
    # in floats and raises OverflowError instead of allocating.
    # The bit operators go for the same reason ('1 << 10**9') and because a
    # coordinate has no use for them.
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.unaryop,
    ast.cmpop,
)

# Which attributes an expression may reach for. Not a convenience: it is what
# makes 'ast.Attribute' safe to allow at all. Emptying '__builtins__' stops
# nothing on its own, because '().__class__.__base__.__subclasses__()' walks
# from any literal to every class in the interpreter - so the defence is that
# no name on this list leads anywhere, every one of them answering with a
# string, a number or a list built out of the value it was asked about.
#
# It exists because the historical '%name:expression%' form is a real thing
# real packages wrote: '//pub/std/metric/cqwarehouse' names its screw interface
# '%size:value[1:value.index('-')]%', reading "M4-0.7" as 4. That used to be an
# unrestricted 'eval', so every name here is one this already allowed.
#
# 'format' and 'format_map' are left out deliberately, not overlooked:
# '"{0.__class__}".format(x)' traverses attributes by name at run time, which
# is the whole of what this list is here to prevent. So are 'encode' and
# 'translate', which answer with something other than text.
SAFE_ATTRIBUTES = frozenset(
    [
        # str
        "capitalize",
        "casefold",
        "center",
        "count",
        "endswith",
        "find",
        "index",
        "isalnum",
        "isalpha",
        "isascii",
        "isdecimal",
        "isdigit",
        "islower",
        "isnumeric",
        "isspace",
        "istitle",
        "isupper",
        "join",
        "ljust",
        "lower",
        "lstrip",
        "partition",
        "removeprefix",
        "removesuffix",
        "replace",
        "rfind",
        "rindex",
        "rjust",
        "rpartition",
        "rsplit",
        "rstrip",
        "split",
        "splitlines",
        "startswith",
        "strip",
        "swapcase",
        "title",
        "upper",
        "zfill",
        # int and float
        "as_integer_ratio",
        "bit_length",
        "conjugate",
        "denominator",
        "imag",
        "is_integer",
        "numerator",
        "real",
    ]
)


# The names in 'SAFE_NAMES' whose answer is always a number. 'max' and 'min' are
# deliberately absent: 'max("a", "b")' is text. So is 'str'.
NUMERIC_FUNCTIONS = frozenset(
    [
        "abs",
        "bool",
        "float",
        "int",
        "len",
        "round",
        "pow",
        "acos",
        "asin",
        "atan",
        "atan2",
        "ceil",
        "cos",
        "degrees",
        "floor",
        "hypot",
        "log",
        "radians",
        "sin",
        "sqrt",
        "tan",
        # Each of these checks that what it is handed is numbers.
        "clamp",
        "lerp",
        "interpolate",
    ]
)

# The attributes from 'SAFE_ATTRIBUTES' whose answer is always a number, whether
# read ('value.real') or called ('value.index("-")').
NUMERIC_ATTRIBUTES = frozenset(
    ["bit_length", "count", "denominator", "find", "imag", "index", "numerator", "real", "rfind", "rindex"]
)


def _is_numeric(node: ast.AST, values: dict[str, Any]) -> bool:
    """Whether this operand is *certainly* a number.

    Certainly, rather than "not obviously text", because this is what decides
    whether a multiplication may run, and the two are not the same question. An
    'ast.Call' is the case that makes the difference: 'str(1)' is a call like any
    other, so reading an unknown form as a number lets '%str(1) * 1000000000%'
    allocate the gigabyte the check exists to prevent. So the answer for
    anything not recognised here is no.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float))  # bool is an int, and 'True * 3' is 3
    if isinstance(node, ast.Name):
        # A parameter is looked up before a constant when the expression runs,
        # so it is asked about first here as well: a parameter called 'E' that
        # holds text is text.
        if node.id in values:
            return isinstance(values[node.id], (int, float))
        return node.id in CAD_CONSTANTS
    if isinstance(node, ast.UnaryOp):
        return _is_numeric(node.operand, values)
    if isinstance(node, ast.BinOp):
        return _is_numeric(node.left, values) and _is_numeric(node.right, values)
    if isinstance(node, ast.IfExp):
        return _is_numeric(node.body, values) and _is_numeric(node.orelse, values)
    if isinstance(node, ast.Compare):
        return True  # a comparison answers True or False, which are numbers
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "pick":
            # A number when every value it picks from is written out as one:
            # 'pick(temper, ['O', 'T6'], [55e6, 276e6])' is certainly a number,
            # 'pick(i, keys, labels)' may be text.
            picked = node.args[2] if len(node.args) == 3 else None
            return isinstance(picked, (ast.List, ast.Tuple)) and all(_is_numeric(v, values) for v in picked.elts)
        if isinstance(node.func, ast.Name):
            return node.func.id in NUMERIC_FUNCTIONS
        if isinstance(node.func, ast.Attribute):
            return node.func.attr in NUMERIC_ATTRIBUTES
        return False
    if isinstance(node, ast.Attribute):
        return node.attr in NUMERIC_ATTRIBUTES
    return False


# Constants that expressions used to have in lower case, and the name each one
# goes by now. Only to say so when one is used: see 'CAD_CONSTANTS'.
RENAMED_CONSTANTS = {"pi": "PI", "e": "E"}


def _check(tree: ast.AST, expression: str, values: dict[str, Any]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in RENAMED_CONSTANTS and node.id not in values:
            raise ExpressionError(
                expression,
                NameError(
                    "'%s' is not defined: a constant is named in upper case, write '%s'"
                    % (node.id, RENAMED_CONSTANTS[node.id])
                ),
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            # Multiplying a sequence repeats it, and the repeat count is the
            # size of the result: "%'x' * 1000000000%" is a gigabyte allocated
            # while a package is being loaded. So both sides have to be provably
            # numbers - not merely "not obviously text", which still let
            # "%str(1) * 1000000000%" through. That is all a coordinate ever
            # multiplies anyway.
            if not (_is_numeric(node.left, values) and _is_numeric(node.right, values)):
                raise ExpressionError(
                    expression,
                    SyntaxError("only numbers may be multiplied, and this is not certainly a number"),
                )
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(
                expression,
                SyntaxError("%s is not allowed in an expression" % type(node).__name__),
            )
        if isinstance(node, ast.Attribute) and node.attr not in SAFE_ATTRIBUTES:
            raise ExpressionError(
                expression, SyntaxError("'%s' is not one of the attributes an expression may read" % node.attr)
            )
        if isinstance(node, ast.Call) and not isinstance(node.func, (ast.Name, ast.Attribute)):
            raise ExpressionError(
                expression, SyntaxError("only the built-in functions and the methods of a value may be called")
            )
        if isinstance(node, ast.Call) and (node.keywords or any(isinstance(a, ast.Starred) for a in node.args)):
            raise ExpressionError(expression, SyntaxError("an expression calls with plain arguments only"))


def _eval(expression: str, values: dict[str, Any], reported: str) -> Any:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(reported, e) from e
    _check(tree, reported, values)
    try:
        return eval(  # nosec B307 - checked above, no builtins, only the object's own parameters
            compile(tree, "<partcad expression>", "eval"),
            {"__builtins__": {}, **SAFE_NAMES},
            dict(values),
        )
    except Exception as e:
        raise ExpressionError(reported, e) from e


def format_value(value: Any) -> str:
    """How an evaluated value reads when it is put back into a string.

    A whole number loses its fraction, because these values end up in *names*:
    a size of 3.0 asks for the sketch 'm;size=3', which is the same instance
    'm;size=3' asked for by hand, while 'm;size=3.0' would be a second one.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


def substitute(text: str, values: dict[str, Any]) -> Any:
    """Resolve every ``%...%`` in one string.

    A string that is nothing but an expression evaluates to the value itself -
    that is what lets a coordinate be written ``"%size / 2%"`` and still be a
    number. Anything else is a string with the values formatted into it.
    """
    whole = PATTERN.fullmatch(text)
    if whole is not None:
        return evaluate(whole.group(1), values)
    return PATTERN.sub(lambda m: format_value(evaluate(m.group(1), values)), text)


def has_expression(value: Any) -> bool:
    """Whether anything in this value carries a ``%...%`` at all."""
    if isinstance(value, str):
        return PATTERN.search(value) is not None
    if isinstance(value, dict):
        return any(has_expression(k) or has_expression(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(has_expression(item) for item in value)
    return False


def resolve(value: Any, values: dict[str, Any], where: str = "") -> Any:
    """Resolve the expressions everywhere inside a declaration.

    Walks strings, lists and dictionaries - keys included, so that a parametrized
    reference can be the *name* of an inherited interface - and leaves everything
    else alone. An expression that cannot be evaluated is reported and left
    standing as the text it was written as: a package that misspells one loses
    that one value rather than failing to load, and the message names the
    expression rather than whatever the unresolved text later fails to be.
    """
    if isinstance(value, str):
        if PATTERN.search(value) is None:
            return value
        try:
            return substitute(value, values)
        except ExpressionError as e:
            pc_logging.error("%s%s" % (where + ": " if where else "", e))
            return value
    if isinstance(value, dict):
        return {resolve(k, values, where): resolve(v, values, where) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(item, values, where) for item in value]
    return value
