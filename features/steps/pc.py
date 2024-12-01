import re
import os
import tempfile
import logging
from behave import given, then

# TODO: @alexanderilyin: consider packaging this into a separate module
# Steps implementations could be distributed separately and reused in different projects


@then('STDOUT should match the regex "{pattern}"')
def step_impl(context, pattern):
    # TODO: @alexanderilyin: consider replace regex with https://pypi.org/project/parse/
    matched = False
    for line in context.result.stdout.splitlines():
        logging.debug(f"Checking line: {line} vs {pattern}")
        if re.match(pattern, line):
            matched = True
            break

    assert matched, "The string does not match the required pattern"


@then('STDERR should match the regex "{pattern}"')
def step_impl(context, pattern):
    # TODO: @alexanderilyin: consider replace regex with https://pypi.org/project/parse/
    matched = False
    for line in context.result.stderr.splitlines():
        logging.debug(f"Checking line: {line} vs {pattern}")
        if re.match(pattern, line):
            matched = True
            break

    assert matched, "The string does not match the required pattern"


@given('"{variable}" env var is set to the temp dir "{directory}"')
def step_impl(context, variable, directory):

    if not hasattr(context, "env"):
        context.env = {}

    os.makedirs(directory, exist_ok=True)
    context.env[variable] = tempfile.mkdtemp(
        prefix="partcad-cli-",
        dir=directory,
    )
    logging.debug(f"Created temporary workspace: {context.env[variable]}")
