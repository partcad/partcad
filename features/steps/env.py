from behave import then, given
from behave.runner import Context
import logging
from features.utils import expandvars  # type: ignore # TODO: @alexanderilyin python.autoComplete.extraPaths


@given('environment variable "{variable}" is set to "{value}"')
def environment_variable_is_set_to(context: Context, variable: str, value: str):
    value = expandvars(value, context)
    logging.debug(f"Set environment variable {variable} to {value}")

    if not hasattr(context, "env"):
        context.env = {}
    context.env[variable] = value
