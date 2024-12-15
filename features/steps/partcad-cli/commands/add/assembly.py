from behave import given, then
from hamcrest import assert_that, equal_to
from features.utils import expandvars  # type: ignore # TODO: @alexanderilyin python.autoComplete.extraPaths
import logging
import yaml
import os


@given('a file named "{filename}" with content')
def step_impl(context, filename):
    content = context.text
    filename = expandvars(filename, context)
    filename = os.path.join(context.test_dir, filename)
    with open(filename, "w") as file:
        logging.debug(f"Creating file: {filename}")
        file.write(content)


@then('a file named "{file_path}" should have YAML content')
def step_impl(context, file_path):
    # TODO: @alexanderilyin: allow use $PWD in the file path
    file_path = os.path.join(context.test_dir, file_path)

    # Parse the expected YAML content from the context
    expected_yaml = yaml.safe_load(context.text)

    # Resolve the file path
    file_path = os.path.expandvars(file_path)

    # Read and parse the actual YAML content from the file
    with open(file_path, "r") as file:
        actual_yaml = yaml.safe_load(file)

    # Compare the dictionaries
    # assert actual_yaml == expected_yaml, f"Expected {expected_yaml}, but got {actual_yaml}"
    assert_that(actual_yaml, equal_to(expected_yaml))
