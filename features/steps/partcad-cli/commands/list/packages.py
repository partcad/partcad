from behave import given
from behave.runner import Context
import os
import logging
import tempfile
import shutil

def remove_readonly(func, path, exc_info):
    try:
        os.chmod(path, 0o777)
        func(path)
    except Exception as e:
        logging.warning("Cannot delete %s: %s", path, e)

@given('I have temporary $HOME in "{directory}"')
def step_impl(context: Context, directory: str) -> None:
    # TODO-70: @alexanderilyin: use dedicated object for test directories
    os.makedirs(directory, exist_ok=True)
    context.home_dir = tempfile.mkdtemp(
        prefix="partcad-cli-",
        dir=directory,
    )
    logging.info("Created temporary home: %s", context.home_dir)

    context.user_config_dir = os.path.join(context.home_dir, ".partcad")
    os.makedirs(context.user_config_dir, exist_ok=True)
    logging.info("Created temporary partcad configuration directory: %s", context.user_config_dir)

    # TODO-71: @alexanderilyin: mention in docs
    # Clean up after the test
    if os.environ.get("BEHAVE_NO_CLEANUP", "0") != "1":
        context.add_cleanup(shutil.rmtree, context.home_dir, onerror=remove_readonly)
