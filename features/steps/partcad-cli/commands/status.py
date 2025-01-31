import os
import re
import yaml
from behave import then


@then('a file named "{filename}" should be created with content')
def step_impl(context, filename):
    expected_content = yaml.safe_load(context.text.strip())
    location = os.path.join(context.test_dir, filename)
    assert os.path.exists(location), f"File {location} does not exist"

    with open(location, "r") as file:
        actual_content = yaml.safe_load(file.read().strip())

    # Regex check for pythonVersion and partcad version
    for key, item in expected_content.items():
        if key in ["pythonVersion", "partcad"] and re.match(item, actual_content[key]):
            expected_content[key] = actual_content[key]
    assert (
        actual_content == expected_content
    ), f"File content does not match.\nExpected:\n{expected_content}\nActual:\n{actual_content}"
