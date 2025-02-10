from behave import then, given
import os
import shutil
import logging

@given(u'a directory named "{directory}" exists')
def step_impl(context, directory):
    """Ensure the specified directory exists inside the test workspace."""
    dir_path = os.path.join(context.test_dir, directory)
    os.makedirs(dir_path, exist_ok=True)
    logging.debug(f"Created directory: {dir_path}")

@given(u'I copy file "{src}" to "{dest}" inside test workspace')
def step_impl(context, src, dest):
    """Copy a file from the project workspace to the test workspace."""
    if not hasattr(context, "test_dir"):
        raise RuntimeError("Test directory (context.test_dir) is not set yet.")

    base_src_path = getattr(context, "project_root", os.getcwd())

    src_path = os.path.join(base_src_path, src)
    dest_path = os.path.join(context.test_dir, dest)

    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source file '{src_path}' does not exist. Check repository path: {base_src_path}")

    shutil.copy(src_path, dest_path)
    logging.debug(f"Copied {src_path} to {dest_path}")

@then(u'a file named "{filename}" should exist')
def step_impl(context, filename):
    """Check if the specified file exists in the test workspace."""
    file_path = os.path.join(context.test_dir, filename)
    assert os.path.exists(file_path), f"File '{file_path}' does not exist!"
    logging.debug(f"File exists: {file_path}")
