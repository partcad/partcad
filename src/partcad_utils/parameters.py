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
"""

import decimal
import re

from .logging import debug

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


def coerce_parameter_value(param_type, param_value, param_name: str, object_name: str):
    """One parameter value, read as the type the parameter declares.

    The values arrive as the strings they were written as - '<name>;size=4' is
    text - and this is where each becomes the number, string or flag it stands
    for.
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
        return param_value
    debug("The parameter '%s' of '%s' has no type; taking '%s' as it is" % (param_name, object_name, param_value))
    return param_value


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
