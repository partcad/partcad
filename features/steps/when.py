from behave import when
from behave.runner import Context
import time
import logging
import os
import subprocess
from features.utils import expandvars  # type: ignore # TODO: @alexanderilyin python.autoComplete.extraPaths


def run(context: Context, command: str):
    command = expandvars(command, context)
    # We need to keep current environment variables
    # TODO: @alexanderilyin: merge this with features/steps/partcad-cli/commands/version.py
    env = dict(os.environ)
    if hasattr(context, "home_dir"):
        # Override the HOME variable
        env["HOME"] = context.home_dir

    cwd = None
    if hasattr(context, "test_dir"):
        cwd = context.test_dir

    # logging.debug(f"ENV: {env}")
    # TODO: @alexanderilyin: make multiline friendly
    logging.debug(f"Running command: {command} in {cwd}")

    start_time = time.time()
    # Run the command in the shell
    result = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )
    end_time = time.time()
    context.duration = end_time - start_time

    logging.debug(f"Command output: {result.stdout}")
    logging.debug(f"Command error: {result.stderr}")
    logging.debug(f"Command return code: {result.returncode}")

    # Store the result in the context for further steps
    context.result = result


@when("I run command")
def i_run_command_multiline(context: Context):
    # TODO: Document that it's better to have 'Uses' rather than 'Depends'
    """
    Provides:
      - context.result: the result of the command
      - context.duration: the duration of the command
    Depends:
      - @given('I am in "{directory}" directory')
    Uses:
      - @given('I have temporary $HOME in "{directory}"')
    """
    run(context, context.text)


@when('I run "{command}"')
def i_run_command_oneline(context: Context, command: str):
    run(context, command)
