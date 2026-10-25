from partcad_utils.parameters import array_item_type, coerce_parameter_value, normalize_parameters  # noqa: F401

from . import expr
from . import logging as pc_logging
from .user_config import user_config as process_user_config


def parameter_overrides(user_config=None) -> dict:
    """The parameter overrides in effect for a context: object name -> {parameter: value}.

    The process-wide configuration's ('pc.user_config', where a program using
    PartCAD as a library sets them), with those of 'user_config' -- the
    configuration the context was built from -- on top, one parameter at a
    time. The two differ in a daemon: it builds every context from its caller's
    configuration (see '_caller_user_config' in the JSON-RPC service), which is
    where '--extra-param' and the caller's '~/.partcad/config.yaml' put theirs,
    while its process-wide one was resolved when it started and has none of
    them. Reading that one alone is how '--extra-param' came to change nothing
    a daemon built.
    """
    overrides = {name: dict(values or {}) for name, values in process_user_config.parameter_config.to_dict().items()}
    if user_config is not None and user_config is not process_user_config:
        for name, values in user_config.parameter_config.to_dict().items():
            overrides.setdefault(name, {}).update(values or {})
    return overrides


def apply_user_parameter_overrides(
    config: dict, object_name: str, section: str = "parameters", user_config=None
) -> dict:
    """Let the user's own configuration override the defaults this object declares.

    A name the object does not declare is reported rather than raised on: an
    interface's 'parameters:' holds two kinds and only the construction half is
    overridable, so a name meant for the other half reaches this as a name that
    is simply not there.

    A value is read as the type the parameter declares, the way a value written
    into an object's name is ('desk;length=60', see 'apply_parameter_values'):
    '--extra-param' hands over text, and '60' used to reach a template as the
    string '60', which multiplies into '606060'. One that cannot be read as its
    type is an error, and the declared default stands.

    'user_config' is the configuration of the context the object belongs to
    (see 'parameter_overrides').
    """
    config_parameters = parameter_overrides(user_config)
    if object_name in config_parameters and section in config and config[section]:
        parameter_config = config_parameters[object_name]
        for param_name in parameter_config:
            if param_name in config[section]:
                declared = config[section][param_name]
                try:
                    value = coerce_parameter_value(
                        declared_parameter_type(declared),
                        parameter_config[param_name],
                        param_name,
                        object_name,
                        item_type=array_item_type(declared),
                    )
                except (ArithmeticError, TypeError, ValueError) as e:
                    pc_logging.error(
                        "The override of the parameter '%s' of '%s' cannot be used: %s" % (param_name, object_name, e)
                    )
                    continue
                declared["default"] = value
            else:
                pc_logging.debug(
                    "The configured parameter '%s' is not declared in '%s' of '%s'" % (param_name, section, object_name)
                )
    return config


class Configuration:
    def __init__(self, name, config) -> None:
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name, user_config=None):
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
        return apply_user_parameter_overrides(config, object_name, user_config=user_config)


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
        declared["default"] = coerce_parameter_value(
            declared.get("type"), param_value, param_name, object_name, item_type=array_item_type(declared)
        )
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
            value = coerce_parameter_value(
                declared_parameter_type(declaration),
                param_value,
                param_name,
                object_name,
                item_type=array_item_type(declaration),
            )
        except Exception:
            canonical[param_name] = param_value
            continue
        if isinstance(value, list):
            # Each item spelled as a value is, and the list left a list: the
            # name writes it with commas (see 'format_parameterized_name').
            canonical[param_name] = [
                item if isinstance(item, (list, dict)) else expr.format_value(item) for item in value
            ]
        else:
            canonical[param_name] = expr.format_value(value)
    return canonical


def normalized_array_values(declarations: dict, values: dict, object_name: str) -> dict:
    """The values a reference gives, with every array value read into the list it is.

    What makes one set of list values one instance, in memory and in the cache,
    however it was handed over: 'include=A,B' in a name, '-p include=A,B', and
    an ASSY link's or the editor's '[A, B]' are all the list ['A', 'B'], in the
    order given, and so all name the instance 'panel;include=A,B' -- where a
    list used to be written into the name as Python prints it, beside the text
    that meant the same. An item is read as the type the declared default's
    items share ('array_item_type'), so the values the shape is keyed on agree
    as well as the name.

    Only arrays: a scalar is named as it was written, as it always has been.
    'declarations' is the object's parameter section, short forms and all, with
    the ones its type contributes; a value that cannot be read is handed back
    as it was, for 'apply_parameter_values' to refuse with its own message.
    """
    normalized = dict(values)
    for param_name, param_value in values.items():
        declaration = (declarations or {}).get(param_name)
        if declared_parameter_type(declaration) != "array":
            continue
        try:
            normalized[param_name] = coerce_parameter_value(
                "array", param_value, param_name, object_name, item_type=array_item_type(declaration)
            )
        except (ArithmeticError, TypeError, ValueError):
            continue
    return normalized


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
