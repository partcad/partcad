from behave import given
from behave.runner import Context
import os
import logging
import tempfile
import shutil


@given('I have temporary $HOME in "{directory}"')
def step_impl(context: Context, directory: str) -> None:
    # TODO: @alexanderilyin: use dedicated object for test directories
    os.makedirs(directory, exist_ok=True)
    context.home_dir = tempfile.mkdtemp(
        prefix="partcad-cli-",
        dir=directory,
    )
    logging.info("Created temporary home: %s", context.home_dir)

    # TODO: @alexanderilyin: mention in docs
    # Clean up after the test
    if os.environ.get("BEHAVE_NO_CLEANUP", "0") != "1":
        context.add_cleanup(shutil.rmtree, context.home_dir)
