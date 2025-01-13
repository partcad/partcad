from behave import given, then
from behave.runner import Context
import yaml
import logging
import tempfile
import os
import shutil


@given('I am in "{directory}" directory')
def step_impl(context: Context, directory):
    """
    Provides:
    - context.test_dir: temporary directory for the test
    """
    # TODO-66: @alexanderilyin: use dedicated object for test directories
    # Create a temporary directory for the test
    os.makedirs(directory, exist_ok=True)
    context.test_dir = tempfile.mkdtemp(
        prefix="partcad-cli-",
        dir=directory,
    )
    logging.debug(f"Created temporary workspace: {context.test_dir}")

    # Changing the current working directory can interfere with Behave's ability to locate feature files and other resources.
    # Therefore, we avoid changing the directory here to prevent such issues.
    # # Change the current working directory to the test directory
    # os.chdir(context.test_dir)

    # Clean up after the test
    # TODO-67: @alexanderilyin: mention in docs
    if os.environ.get("BEHAVE_NO_CLEANUP", "0") != "1":
        context.add_cleanup(shutil.rmtree, context.test_dir)


@then('a file named "{filename}" should be created')
def step_impl(context, filename):
    # Check if the file exists in the current directory
    file_path = os.path.join(context.test_dir, filename)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File '{filename}' was not created")


@given('a file named "{filename}" does not exist')
def step_impl(context, filename):
    file_path = os.path.join(context.test_dir, filename)

    # Check if the file does not exist
    assert not os.path.isfile(file_path), f"File '{filename}' should not exist"


# @then('the file "{filename}" should contain valid YAML')
# def step_impl(context, filename):
#     file_path = os.path.join(context.test_dir, filename)

#     # Check if the file exists
#     assert os.path.isfile(file_path), "File '%' was not created" % filename

#     # Read and parse the YAML content
#     with open(file_path, "r") as file:
#         try:
#             yaml_content = yaml.safe_load(file)
#             logging.debug(f"YAML content: {yaml_content}")
#             assert yaml_content is not None, "YAML content is empty or invalid"

#             # Check the structure of the YAML content
#             # TODO-68: @alexanderilyin: move this to a separate step
#             expected_structure = {"dependencies", "sketches", "parts", "assemblies"}
#             assert expected_structure.issubset(yaml_content.keys()), "YAML content does not match expected structure"

#             # # Check that pub repo we added
#             # expected_content = {
#             #     "dependencies": {"pub": {"type": "git", "url": "https://github.com/openvmp/partcad-index.git"}}
#             # }
#             # assert yaml_content == expected_content, "YAML content does not match expected private package structure"
#         except yaml.YAMLError as exc:
#             assert False, f"Error parsing YAML content: {exc}"


@then("the package should be marked as private")
def step_impl(context):
    """
    TODO-69: @alexanderilyin: -p flag is confusing, it only drops the 'import.pub' section
    """
    file_path = os.path.join(context.test_dir, "partcad.yaml")

    # Check if the file exists
    assert os.path.isfile(file_path), "File 'partcad.yaml' was not created"

    # Read and parse the YAML content
    with open(file_path, "r") as file:
        try:
            yaml_content = yaml.safe_load(file)
            if yaml_content is None:
                raise ValueError("YAML content is empty or invalid")

            # Check if the 'import.pub' key is not present
            import_section = yaml_content.get("dependencies")
            import_missing = import_section is None
            import_without_pub = import_section is not None and "pub" not in import_section
            if not (import_missing or import_without_pub):
                raise ValueError("'import.pub' key should not be present")
        except yaml.YAMLError as exc:
            raise ValueError(f"Error parsing YAML content: {exc}") from exc
