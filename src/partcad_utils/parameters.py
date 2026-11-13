#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a parameter declaration means, in the one place both ends read it.

PartCAD expands a declaration as it loads a package (see 'partcad.config'), and
a client that checks a file an editor has open expands it too, to render that
file with the values PartCAD would (see 'partcad_utils.assy_lint'). Neither may
have its own reading of 'size: 3', and the client must not import the CAD kernel
to share this one -- which is why it lives here.

The values a request assigns ('-p'/'--param') are read here for the same
reason: 'pc' checks them before sending, the MCP server writes them, and the
daemon reads them, and three readings of '<name>=<value>' would be three answers.

So is what 'shared: true' on a declaration means -- a package-level parameter,
one value for every object of the package that declares it -- and the rule that
every declaration of one name in a package agrees about it: PartCAD refuses a
package that breaks it as it loads the package, and 'pc lint' and the editor
report it where it is written (see 'shared_parameter_problems').
"""

import copy
import decimal
import re
from typing import Mapping, NamedTuple, Optional

from .logging import debug
from .utils import format_parameterized_name

# One override as written: '<object>.<parameter>=<value>'. The parameter is the
# first '.<name>=' in it -- a run with neither '.' nor '=' between a '.' and an
# '=' -- so the object's name before it may have dots of its own
# ('//pub/v1.2:bracket.v2') and the value after it anything at all ('v1.2',
# 'a=b'). An object's name holds no '.<name>=': the only '=' it can have comes
# after a parameter's name in it ('desk;length=60'), and that has no '.'.
_OVERRIDE = re.compile(r"^(?P<object>.+?)\.(?P<parameter>[^.=]+)=(?P<value>.*)$", re.DOTALL)


def normalize_parameters(parameters: dict) -> dict:
    """Expand the short forms of one parameter declaration section.

    A parameter may be declared as the bare value it defaults to - a number, a
    string, a boolean, a list - and this turns each of those into the long form
    the rest of PartCAD reads: a dictionary with a 'type' and a 'default'.

    Lifted out of 'partcad.config.Configuration.normalize' because an interface's
    'parameters:' holds these beside its freedom of movement and expands only
    that half (see 'partcad.interface_config'), and two copies of these rules
    would be two answers to "what does 'size: 3' mean".
    """
    if not isinstance(parameters, dict):
        return parameters

    for param_name, param_value in parameters.items():
        # Expand short formats
        if isinstance(param_value, str):
            parameters[param_name] = {
                "type": "string",
                "default": param_value,
            }
        elif isinstance(param_value, bool):
            parameters[param_name] = {
                "type": "bool",
                "default": param_value,
            }
        elif isinstance(param_value, float):
            parameters[param_name] = {
                "type": "float",
                "default": param_value,
            }
        elif isinstance(param_value, int):
            parameters[param_name] = {
                "type": "int",
                "default": param_value,
            }
        elif isinstance(param_value, list):
            parameters[param_name] = {
                "type": "array",
                "default": param_value,
            }
        # All params are float unless another type is explicitly specified
        elif isinstance(param_value, dict) and "type" not in param_value:
            param_value["type"] = "float"

    return parameters


# The types a parameter is declared as, which a value is read as (see
# 'coerce_parameter_value'). A freedom-of-movement parameter of an interface is
# 'move' or 'turn' instead, and never one of these (see 'is_movement_parameter').
VALUE_TYPES = ("string", "int", "bool", "float", "array")

# The two of them that are quantities, and so may be bounded.
NUMERIC_TYPES = ("int", "float")

# What a numeric parameter states its range in, both ends included.
BOUNDS = ("min", "max")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _spelled(value) -> str:
    # A whole float as the integer it is, the way an expression writes one
    # into a name: a bound of 45 is not refused as '45.0'.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format_assignment(value)


def declaration_problems(declaration, param_name: str, object_name: str) -> list:
    """What is wrong with the bounds, the 'enum' and the default of one expanded parameter declaration, as messages.

    'min' and 'max' bound a number, so only an 'int' or a 'float' parameter
    states them, each a number, the one not above the other; and the default is
    a value like any other, so it lies within them and is one of what 'enum'
    allows. Read by PartCAD as it loads an object (see
    'partcad.config.check_parameter_declarations') and by the linter
    ('assy_lint.check_parameter_bounds'), in the same words.
    """
    if not isinstance(declaration, dict):
        return []
    problems = _bounds_problems(declaration, param_name, object_name)
    if not problems and "default" in declaration:
        problem = enum_problem(declaration, declaration["default"], param_name, object_name, default=True)
        if problem is not None:
            problems.append(problem)
    return problems


def value_problem(declaration, value, param_name: str, object_name: str) -> Optional[str]:
    """Why a value given to a parameter - by a reference, by an override - is not one it may take, or None.

    Outside the range a numeric parameter declares ('bound_problem'), or not
    one of the values its 'enum' allows ('enum_problem'). The one check every
    kind of object's values go through ('partcad.config.apply_parameter_values').
    """
    return bound_problem(declaration, value, param_name, object_name) or enum_problem(
        declaration, value, param_name, object_name
    )


def _quoted(value) -> str:
    return "'%s'" % value if isinstance(value, str) else _spelled(value)


def enum_problem(declaration, value, param_name: str, object_name: str, default: bool = False) -> Optional[str]:
    """Why 'value' is not one of the values a parameter's 'enum' allows, or None if it is (or there is no 'enum').

    A value and an allowed one are compared as a name spells them, so the
    integer 3 is the '3' an 'enum' of text lists. An array is not checked: an
    'enum' lists single values.
    """
    if not isinstance(declaration, dict):
        return None
    allowed = declaration.get("enum")
    if not isinstance(allowed, (list, tuple)) or not allowed:
        return None
    if value is None or isinstance(value, (list, tuple, dict)) or declaration.get("type") == "array":
        return None
    if value in allowed or _spelled(value) in {_spelled(each) for each in allowed}:
        return None
    listed = ", ".join(_quoted(each) for each in allowed)
    if default:
        return "The parameter '%s' of '%s' defaults to %s, and its 'enum' allows %s" % (
            param_name,
            object_name,
            _quoted(value),
            listed,
        )
    return "The parameter '%s' of '%s' cannot be %s: its 'enum' allows %s" % (
        param_name,
        object_name,
        _quoted(value),
        listed,
    )


def _bounds_problems(declaration: dict, param_name: str, object_name: str) -> list:
    """What is wrong with a declaration's 'min' and 'max', and with its default against them."""
    if not any(bound in declaration for bound in BOUNDS):
        return []
    kind = declaration.get("type", "float")
    if kind not in NUMERIC_TYPES:
        return [
            "The parameter '%s' of '%s' is a%s %s, and only an int or a float parameter states a 'min' or a 'max'"
            % (param_name, object_name, "n" if kind[:1] in "aeiou" else "", kind)
        ]
    problems = []
    for bound in BOUNDS:
        if bound in declaration and not _is_number(declaration[bound]):
            problems.append(
                "The '%s' of the parameter '%s' of '%s' is %r, not a number"
                % (bound, param_name, object_name, declaration[bound])
            )
    if problems:
        return problems
    low, high = declaration.get("min"), declaration.get("max")
    if low is not None and high is not None and low > high:
        return [
            "The parameter '%s' of '%s' has a 'min' of %s above its 'max' of %s: no value is both"
            % (param_name, object_name, _spelled(low), _spelled(high))
        ]
    if "default" in declaration:
        problem = bound_problem(declaration, declaration["default"], param_name, object_name, default=True)
        if problem is not None:
            problems.append(problem)
    return problems


def bound_problem(declaration, value, param_name: str, object_name: str, default: bool = False) -> Optional[str]:
    """Why 'value' is outside the range a numeric parameter declares, or None if it is not.

    The bounds are inclusive. 'default' says the value is the one the
    declaration defaults to rather than one a reference gave, which is all that
    changes about the message. A value that is not a number is not this
    function's to report: reading it as the declared type is what fails on it.
    """
    if not isinstance(declaration, dict) or declaration.get("type", "float") not in NUMERIC_TYPES:
        return None
    if not _is_number(value):
        return None
    low, high = declaration.get("min"), declaration.get("max")
    for bound, outside in (("min", _is_number(low) and value < low), ("max", _is_number(high) and value > high)):
        if not outside:
            continue
        limit = _spelled(declaration[bound])
        if default:
            return "The parameter '%s' of '%s' defaults to %s, and its '%s' is %s" % (
                param_name,
                object_name,
                _spelled(value),
                bound,
                limit,
            )
        return "The parameter '%s' of '%s' cannot be %s: its '%s' is %s" % (
            param_name,
            object_name,
            _spelled(value),
            bound,
            limit,
        )
    return None


def coerce_parameter_value(param_type, param_value, param_name: str, object_name: str, item_type=None):
    """One parameter value, read as the type the parameter declares.

    The values arrive as the strings they were written as - '<name>;size=4' is
    text - and this is where each becomes the number, string or flag it stands
    for.

    An array is a list however it was written: 'include=A,B' in a name, a list
    or a tuple an ASSY link, the editor or an agent handed over (see
    'as_list'), in the order its items were given. Each item is read as
    'item_type', the type the items of the declared default share (see
    'array_item_type'); with no such type declared it is text, which is the one
    thing every way of writing an item can agree on. That is what makes
    'include=A,B' and '[A, B]' one value to the cache, which keys a shape on
    its parameters' values and not on its name.
    """
    if param_type == "string":
        return str(param_value)
    if param_type == "int":
        # A whole number written as one ('4.0', which is what a YAML value of
        # 4.0 spells) is what was meant; anything with a fraction is not an
        # integer and is refused rather than silently truncated. Through
        # 'Decimal' rather than 'float' so that neither the test nor the value
        # loses precision on a large integer.
        value = decimal.Decimal(str(param_value))
        if value != value.to_integral_value():
            raise ValueError(
                "The parameter '%s' of '%s' is an integer, and '%s' is not one" % (param_name, object_name, param_value)
            )
        return int(value)
    if param_type == "float":
        return float(param_value)
    if param_type == "bool":
        if isinstance(param_value, str):
            return param_value.lower() == "true"
        return bool(param_value)
    if param_type == "array":
        return [_array_item(item_type, item, param_name, object_name) for item in as_list(param_value)]
    debug("The parameter '%s' of '%s' has no type; taking '%s' as it is" % (param_name, object_name, param_value))
    return param_value


def _array_item(item_type, item, param_name: str, object_name: str):
    """One item of an array, read as the declared item type, or as text when none is declared."""
    if isinstance(item, (list, tuple, dict)):
        # A nested value is kept as it is: a name cannot spell one, so there is
        # nothing it has to agree with.
        return list(item) if isinstance(item, tuple) else item
    if item_type is None:
        return item if isinstance(item, str) else format_assignment(item)
    return coerce_parameter_value(item_type, item, param_name, object_name)


def as_list(value) -> list:
    """A list-valued parameter, however it was written.

    A list stays one, in its own order, and a tuple becomes one; text is the
    spelling a reference has to use, because the whole parameter section of a
    name is text, so it is split on commas. Empty entries are dropped rather
    than kept as empty names: a trailing comma is a typo, not a layer called
    ''.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value]


def _scalar_type(value):
    """The parameter type a single value is, or None for one that is not a scalar."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return None


def array_item_type(declaration):
    """The type an array parameter's items are read as: the one its declared default's items share.

    A declaration says what an array holds by example. 'sizes: [10, 20]' is an
    array of integers, so 'sizes=30,40' is [30, 40] rather than two strings,
    exactly as an ASSY link's 'sizes: [30, 40]' is; whole numbers and fractions
    together are floats. A default that is empty, mixed, or not there says
    nothing, and the items are then read as text (see 'coerce_parameter_value').
    """
    default = declaration.get("default") if isinstance(declaration, dict) else declaration
    if not isinstance(default, (list, tuple)) or not default:
        return None
    kinds = {_scalar_type(item) for item in default}
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds == {"int", "float"}:
        return "float"
    return None


def parse_override(text: str) -> tuple:
    """One parameter override as written on a command line: (object, parameter, value).

    '//pub/furniture:desk.length=60' is ('//pub/furniture:desk', 'length',
    '60'). The value is the text as written; what it means is the declared type
    of the parameter it lands on (see 'coerce_parameter_value'). Raises
    ``ValueError`` for anything that does not name an object, a parameter and a
    value.
    """
    match = _OVERRIDE.match(text or "")
    if match is None or not match.group("object").strip() or not match.group("parameter").strip():
        raise ValueError("'%s' is not '<object>.<parameter>=<value>'" % text)
    return match.group("object"), match.group("parameter"), match.group("value")


def assignments(value) -> dict:
    """The parameter values a request assigns to the object it names, by parameter.

    What '-p'/'--param' on the command line arrives as, under the request's
    'params'. Two shapes mean the same thing there: a list of '<name>=<value>'
    strings, which is what 'pc' sends, and a mapping, which is what the editor
    extension, the FreeCAD addon and an agent send. Read here so that the two
    ends, and every method on the daemon, read them one way.

    A string with no '=' in it is refused rather than passed over. It used to be
    passed over, so that 'pc info -p width' quietly showed the object with its
    default width.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        result = {}
        for item in value:
            name, separator, text = str(item).partition("=")
            if not separator or not name:
                raise ValueError("'%s' is not '<name>=<value>'" % item)
            result[name] = text
        return result
    raise ValueError("Parameter values are a mapping or a list of '<name>=<value>', not %r" % (value,))


def format_assignment(value) -> str:
    """One assigned value, written the way an object's name spells it.

    A list is its items joined by commas, which is how a name holds one
    ('bends;include=BEND_UP,BEND_DOWN', see 'parse_parameterized_name'), and a
    flag is 'true' or 'false', which is what 'coerce_parameter_value' reads back.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(format_assignment(item) for item in value)
    return str(value)


def assign(name: str, values) -> str:
    """The name of the instance of 'name' with these parameter values.

    'pc render bolt -p length=10' asks for exactly what 'pc render
    "bolt;length=10"' asks for, and this is what makes the two one request: an
    instance of an object *is* its name with the values written into it. A value
    assigned here takes precedence over one the name already carries, the way an
    outer reference takes precedence everywhere (see
    'format_parameterized_name'). 'values' is either shape 'assignments' reads.
    """
    values = assignments(values)
    if not values:
        return name
    return format_parameterized_name(name, {key: format_assignment(value) for key, value in values.items()})


# ---- package-level (shared) parameters -------------------------------------
#
# A declaration that says 'shared: true' is not a parameter of its object alone:
# it is a parameter of the package, and every object of the package that
# declares a parameter of that name with 'shared: true' has the one value. The
# motivating case is a package of plugins for one website -- a repository and a
# provider that need the same API token -- where logging in once has to serve
# both. See 'partcad.shared_parameters' for how PartCAD holds the value.

# The key a declaration says it is shared with. Absent means false.
SHARED = "shared"

# The keys shared declarations of one name may differ in: what a person reads
# about the parameter, never what it is or what it is worth.
SHARED_MAY_DIFFER = ("desc", "description")

# The kinds of object a 'partcad.yaml' declares parameters on, and the section
# each is declared in. Materials, colours and finishes are parametric too, but a
# value of theirs names a declaration rather than configuring one, and none of
# them is ever a client of anything: they are not shared.
PARAMETERIZED_SECTIONS = {
    "interface": "interfaces",
    "sketch": "sketches",
    "part": "parts",
    "assembly": "assemblies",
    "scene": "scenes",
    "software": "software",
    "provider": "providers",
    "repository": "repositories",
}

# The movement parameters that need no 'dir' because their axis is in their
# name. Both spellings: an interface's own 'parameters:' uses 'moveX' and a
# 'mates:' section uses 'move-x', and both have always been accepted.
MOVEMENT_PARAMETER_NAMES = frozenset(
    ["move%s" % axis for axis in "XYZ"]
    + ["turn%s" % axis for axis in "XYZ"]
    + ["move-%s" % axis for axis in "xyz"]
    + ["turn-%s" % axis for axis in "xyz"]
)

# The keys that only a freedom-of-movement parameter has, and the two values of
# 'type' that only it uses.
MOVEMENT_PARAMETER_KEYS = ("min", "max", "dir")
MOVEMENT_PARAMETER_TYPES = ("move", "turn")


def is_movement_parameter(name: str, declaration) -> bool:
    """Whether an entry of an interface's 'parameters:' is freedom of movement rather than a value.

    See 'partcad.interface_config' for the rules, which this reads in order. A
    movement parameter is what a connection may still do, never a value an
    object is built with, so it is never shared.
    """
    if name in MOVEMENT_PARAMETER_NAMES:
        return True
    if isinstance(declaration, (list, tuple)):
        return True
    if isinstance(declaration, dict):
        if declaration.get("type") in VALUE_TYPES:
            # Says what kind of value it is, which a freedom of movement never
            # does ('move' or 'turn'): a construction parameter, bounded by its
            # 'min' and 'max' as any numeric one may be.
            return False
        if any(key in declaration for key in MOVEMENT_PARAMETER_KEYS):
            return True
        if declaration.get("type") in MOVEMENT_PARAMETER_TYPES:
            return True
    return False


def is_shared(declaration) -> bool:
    """Whether a parameter declaration is a package-level one ('shared: true')."""
    return isinstance(declaration, dict) and declaration.get(SHARED) is True


class Declaration(NamedTuple):
    """One declaration of a parameter: the object declaring it, and what it says, expanded."""

    kind: str
    object: str
    declaration: dict


def parameter_declarations(sections: Mapping) -> dict:
    """Every parameter declaration of a package, by parameter name.

    ``sections`` maps a kind of :data:`PARAMETERIZED_SECTIONS` to that kind's
    declarations as ``{object: config}``; a kind that is absent or None is left
    out. Each declaration is an expanded copy (see 'normalize_parameters'), so
    'size: 3' and '{type: int, default: 3}' are the same declaration. An
    interface's freedom of movement is left out (see 'is_movement_parameter').
    """
    found = {}
    for kind in PARAMETERIZED_SECTIONS:
        declarations = sections.get(kind)
        if not isinstance(declarations, Mapping):
            continue
        for object_name, config in declarations.items():
            if not isinstance(config, Mapping):
                continue
            declared = config.get("parameters")
            if not isinstance(declared, Mapping):
                continue
            for param_name, declaration in declared.items():
                if kind == "interface" and is_movement_parameter(param_name, declaration):
                    continue
                expanded = normalize_parameters({param_name: copy.deepcopy(declaration)})[param_name]
                if not isinstance(expanded, dict):
                    continue
                found.setdefault(param_name, []).append(Declaration(kind, str(object_name), expanded))
    return found


def comparable(declaration: dict) -> dict:
    """What shared declarations of one name have to agree on: everything but 'SHARED_MAY_DIFFER'."""
    return {key: value for key, value in declaration.items() if key not in SHARED_MAY_DIFFER}


def differences(first: dict, second: dict, ignore=()) -> list:
    """The keys two declarations say different things about, sorted, leaving out 'ignore'."""
    one, other = comparable(first), comparable(second)
    return sorted(key for key in set(one) | set(other) if key not in ignore and one.get(key) != other.get(key))


class SharedProblem(NamedTuple):
    """Declarations of one parameter name that a package may not have together.

    ``declarations`` are all of the package's declarations of ``name``: each is
    refused, since which of them is the mistake is the author's to say.
    """

    name: str
    declarations: list
    message: str


def _objects(declarations) -> str:
    named = ["the %s '%s'" % (d.kind, d.object) for d in declarations]
    if len(named) == 1:
        return named[0]
    return ", ".join(named[:-1]) + " and " + named[-1]


def shared_parameter_problems(declarations: Mapping) -> list:
    """The parameter names a package declares in ways that cannot be one shared parameter.

    ``declarations`` is what 'parameter_declarations' answers. Within one
    package every declaration of a name agrees on 'shared': all of them say
    'shared: true', or none of them does -- a name that is one value for some
    objects and a value of its own for others would mean two things depending
    on which object it was set through. And the shared declarations of a name
    are one parameter, so they agree on everything else too -- its 'type', its
    'default', its 'enum' -- and may differ only in 'desc'.

    Read by PartCAD as it loads a package (see
    'Project._refuse_shared_parameter_disagreements') and by the linter
    ('assy_lint.check_shared_parameters'), so that both say the same thing in
    the same words.
    """
    problems = []
    for name, found in declarations.items():
        shared = [d for d in found if is_shared(d.declaration)]
        if not shared:
            continue
        if len(shared) != len(found):
            others = [d for d in found if not is_shared(d.declaration)]
            problems.append(
                SharedProblem(
                    name,
                    list(found),
                    "The parameter '%s' is declared 'shared: true' by %s, and not by %s: every declaration of a "
                    "parameter in one package says 'shared: true', or none of them does (absent is false)"
                    % (name, _objects(shared), _objects(others)),
                )
            )
            continue
        first = shared[0]
        for other in shared[1:]:
            keys = differences(first.declaration, other.declaration)
            if keys:
                problems.append(
                    SharedProblem(
                        name,
                        list(found),
                        "The shared parameter '%s' is declared differently by %s and %s (%s): the shared "
                        "declarations of a name are one parameter, and may differ only in 'desc'"
                        % (name, _objects([first]), _objects([other]), ", ".join("'%s'" % k for k in keys)),
                    )
                )
                break
    return problems


class SharedValue(NamedTuple):
    """What the user's configuration sets a shared parameter to.

    ``found`` says whether it sets it at all, and ``value`` is then the value as
    written (the declared type reads it, see 'coerce_parameter_value').
    ``source`` is the entry it came from. ``conflict`` says why the per-object
    entries were passed over, when they disagree.
    """

    found: bool
    value: object = None
    source: Optional[str] = None
    conflict: Optional[str] = None


def shared_override(package_name: str, param_name: str, sharers, overrides: Mapping) -> SharedValue:
    """The value the user's overrides give the shared parameter 'param_name' of a package.

    ``overrides`` is object name -> {parameter: value}, the 'parameters:' of
    '~/.partcad/config.yaml' with '--extra-param' on top
    ('partcad.config.parameter_overrides'); ``sharers`` the names, within the
    package, of the objects sharing the parameter. Two kinds of entry set it:

    - one per object, as for any parameter ('<package>:<object>'). Setting it
      through any of the objects that share it sets it for all of them, so every
      one of their entries is read, not only the entry of the object asked
      about;
    - one for the whole package ('<package>', with no object), which is where
      'pc login' saves a shared credential.

    An object's entry is the more specific of the two and wins, which is what
    makes '--extra-param <package>:<object>.<parameter>=...' work over a value
    the configuration file sets for the package. Two object entries that
    disagree cannot both be the package's value, and neither is guessed
    between: both are passed over, with ``conflict`` saying so, and the
    package's entry or the declared default stands.
    """
    package_entry = overrides.get(package_name)
    per_object = []
    for sharer in sharers:
        key = "%s:%s" % (package_name, sharer)
        entry = overrides.get(key)
        if isinstance(entry, Mapping) and param_name in entry:
            per_object.append((key, entry[param_name]))
    conflict = None
    if per_object:
        values = {_comparable_value(value) for _key, value in per_object}
        if len(values) == 1:
            return SharedValue(True, per_object[0][1], per_object[0][0])
        conflict = (
            "The shared parameter '%s' of '%s' is set to different values for %s: it is one value for all of "
            "them, so none of these is used. Set it once, under 'parameters: %s:' in your configuration"
            % (param_name, package_name, ", ".join("'%s'" % key for key, _value in per_object), package_name)
        )
    if isinstance(package_entry, Mapping) and param_name in package_entry:
        return SharedValue(True, package_entry[param_name], package_name, conflict)
    return SharedValue(False, conflict=conflict)


def _comparable_value(value):
    # What two entries are compared by: their text, so that '4' typed on a
    # command line and 4 written in YAML are one value, and lists hash.
    if isinstance(value, (list, tuple)):
        return tuple(_comparable_value(item) for item in value)
    return format_assignment(value)


def package_of(object_name: str) -> str:
    """The package an object's full name ('//pub/x:bolt') is in: everything before the first ':'.

    A package's name holds no ':' of its own, so the first one is where the
    object's name starts.
    """
    return object_name.partition(":")[0]


def place_saved_overrides(entries, object_name: str, values: Mapping, package_name: str = None, shared=()) -> None:
    """Put the values 'pc login' saves for 'object_name' where they will be read, in 'entries'.

    ``entries`` is the 'parameters:' of a user's configuration, as a mutable
    mapping of object name -> {parameter: value}. A value for a parameter in
    ``shared`` is a value of the package's, so it goes under the package's own
    entry (``package_name``), and every object entry of that package that sets
    the parameter loses it: those are more specific and would win
    ('shared_override'), so a value saved by an earlier login through another
    of the objects would otherwise go on being used, or conflict with this one.
    Every other value goes under the object, as it always has. An object entry
    left with nothing in it is removed.
    """
    shared = set(shared or ()) if package_name else set()
    own = {name: value for name, value in values.items() if name not in shared}
    common = {name: value for name, value in values.items() if name in shared}
    if common:
        prefix = package_name + ":"
        for key in list(entries.keys()):
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            entry = entries[key]
            if not isinstance(entry, Mapping):
                continue
            stale = [name for name in common if name in entry]
            if not stale:
                continue
            remaining = {name: value for name, value in entry.items() if name not in common}
            if not remaining:
                del entries[key]
                continue
            for name in stale:
                del entry[name]
        _merge_entry(entries, package_name, common)
    if own:
        _merge_entry(entries, object_name, own)


def _merge_entry(entries, key: str, values: Mapping) -> None:
    entry = entries.get(key) if hasattr(entries, "get") else None
    if entry is None:
        entries[key] = dict(values)
        return
    if not isinstance(entry, Mapping):
        raise ValueError("'parameters: %s' is not a mapping" % key)
    for name, value in values.items():
        entry[name] = value
