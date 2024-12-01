import re
import os
import tempfile
import logging

from behave import given, then  # type: ignore

# TODO: @alexanderilyin: consider packaging this into a separate module
# Steps implementations could be distributed separately and reused in different projects


def _check_output(output: str, pattern: str) -> bool:
    """Check if any line in the output matches the pattern."""
    return any(re.match(pattern, line) for line in output.splitlines())


@then('STDOUT should match the regex "{pattern}"')
def step_impl(context, pattern):  # type: ignore
    assert _check_output(context.result.stdout, pattern), "STDOUT does not match the required pattern"


@then('STDERR should match the regex "{pattern}"')
def step_impl(context, pattern):  # type: ignore
    # TODO: @alexanderilyin: consider replace regex with https://pypi.org/project/parse/
    matched = False
    for line in context.result.stderr.splitlines():
        logging.debug(f"Checking line: {line} vs {pattern}")
        if re.match(pattern, line):
            matched = True
            break

    assert matched, "The string does not match the required pattern"


@given('"{variable}" env var is set to the temp dir "{directory}"')
def step_impl(context, variable, directory):  # type: ignore
    """Set up temporary directory and assign it to an environment variable."""
    if not hasattr(context, "env"):
        context.env = {}

    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"Failed to create directory {directory}: {e}")

    context.env[variable] = tempfile.mkdtemp(
        prefix="partcad-cli-",
        dir=directory,
    )
    logging.debug(f"Created temporary workspace: {context.env[variable]}")
