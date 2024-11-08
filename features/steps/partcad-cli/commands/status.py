import os
import yaml
from behave import given, when, then


@then('a file named "{filename}" should be created with content')
def step_impl(context, filename):
    expected_content = yaml.safe_load(context.text.strip())
    location = os.path.join(context.test_dir, filename)
    assert os.path.exists(location), f"File {location} does not exist"

    with open(location, "r") as file:
        actual_content = yaml.safe_load(file.read().strip())

    assert (
        actual_content == expected_content
    ), f"File content does not match.\nExpected:\n{expected_content}\nActual:\n{actual_content}"
