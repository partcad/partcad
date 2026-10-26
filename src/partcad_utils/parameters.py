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
"""

import decimal
import re

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
