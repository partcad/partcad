import decimal

from . import expr
from . import logging as pc_logging
from .user_config import user_config


def normalize_parameters(parameters: dict) -> dict:
    """Expand the short forms of one parameter declaration section.

    A parameter may be declared as the bare value it defaults to - a number, a
    string, a boolean, a list - and this turns each of those into the long form
    the rest of PartCAD reads: a dictionary with a 'type' and a 'default'.

    Lifted out of 'Configuration.normalize' below because an interface's
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


def apply_user_parameter_overrides(config: dict, object_name: str, section: str = "parameters") -> dict:
    """Let the user's own configuration override the defaults this object declares.

    A name the object does not declare is reported rather than raised on: an
    interface's 'parameters:' holds two kinds and only the construction half is
    overridable, so a name meant for the other half reaches this as a name that
    is simply not there.
    """
    config_parameters = user_config.parameter_config.to_dict()
    if object_name in config_parameters and section in config and config[section]:
        parameter_config = config_parameters[object_name]
        for param_name in parameter_config:
            if param_name in config[section]:
                config[section][param_name]["default"] = parameter_config[param_name]
            else:
                pc_logging.debug(
                    "The configured parameter '%s' is not declared in '%s' of '%s'" % (param_name, section, object_name)
                )
    return config


class Configuration:
    def __init__(self, name, config) -> None:
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if config is None:
            config = {}

        # Instead of passing the name as a parameter,
        # enrich the configuration object
        # TODO(clairbee): reconsider passing the name as a parameter
        config["name"] = name
        config["orig_name"] = name

        if "parameters" in config:
            normalize_parameters(config["parameters"])

        # Override parameters with user configuration
        return apply_user_parameter_overrides(config, object_name)


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
    pc_logging.debug(
        "The parameter '%s' of '%s' has no type; taking '%s' as it is" % (param_name, object_name, param_value)
    )
    return param_value


def apply_parameter_values(parameters: dict, values: dict, object_name: str) -> dict:
    """Set the defaults of a parameter section from the values a reference names.

    Shared by every parametrizable kind: a part, a sketch and an assembly
    parametrized through 'Project.get_object', and an interface through
    'Project.get_interface'. One copy, because two would be two answers to what
    ';size=4' means.
    """
    for param_name, param_value in values.items():
        declared = parameters.get(param_name)
        if declared is None:
            raise ValueError("The parameter '%s' is not declared in '%s'" % (param_name, object_name))
        declared["default"] = coerce_parameter_value(declared.get("type"), param_value, param_name, object_name)
    return parameters


def declared_parameter_type(declaration):
    """The type of a parameter as declared, expanded or not.

    'normalize_parameters' writes the type into the declaration, but a package
    fetched one object at a time reaches a reader before that has happened -
    and a name has to be canonicalized before anything is built from it. The
    rules are the ones above, read rather than written.
    """
    if isinstance(declaration, dict):
        return declaration.get("type", "float")
    if isinstance(declaration, bool):
        return "bool"
    if isinstance(declaration, str):
        return "string"
    if isinstance(declaration, float):
        return "float"
    if isinstance(declaration, int):
        return "int"
    if isinstance(declaration, list):
        return "array"
    return None


def canonical_parameter_values(parameters: dict, values: dict, object_name: str) -> dict:
    """The values as they should be spelled in the name of the instance.

    '4' and '4.0' are one value of a float parameter, and a name built from one
    of them has to be the name built from the other: the instance's name is its
    identity, and for an interface it is also what a mating is registered
    under. So the text goes through the type it is declared as and comes back
    the way 'partcad.expr' would have written it, which is also how an
    expression that produced it spelled it.

    A value that cannot be read as its declared type is handed back untouched;
    it is not this function's job to report it, and 'apply_parameter_values'
    raises on the same value moments later with the message to show.
    """
    canonical = {}
    for param_name, param_value in values.items():
        declaration = (parameters or {}).get(param_name)
        if declaration is None:
            canonical[param_name] = param_value
            continue
        try:
            value = coerce_parameter_value(declared_parameter_type(declaration), param_value, param_name, object_name)
        except Exception:
            canonical[param_name] = param_value
            continue
        canonical[param_name] = expr.format_value(value)
    return canonical


def parameter_values(parameters: dict) -> dict:
    """The current value of every parameter in a declaration section."""
    if not parameters:
        return {}
    values = {}
    for param_name, declared in parameters.items():
        if isinstance(declared, dict):
            if "default" in declared:
                values[param_name] = declared["default"]
        else:
            # A section that was never normalized (a configuration built in
            # code rather than read from 'partcad.yaml'): the declaration is
            # the value.
            values[param_name] = declared
    return values
