from behave import when, given
from behave.runner import Context
import time
import logging
import os
import subprocess
from features.utils import expandvars  # type: ignore # TODO: @alexanderilyin python.autoComplete.extraPaths


def run(context: Context, command: str):
    if command.startswith("pc "):
        command = f"coverage run --rcfile=$PARTCAD_ROOT/dev-tools/coverage.rc --data-file=$PARTCAD_ROOT/.coverage --parallel -m partcad_cli.click.command {command[3:]}"
    elif command.startswith("partcad "):
        command = f"coverage run --rcfile=$PARTCAD_ROOT/dev-tools/coverage.rc --data-file=$PARTCAD_ROOT/.coverage --parallel -m partcad_cli.click.command {command[8:]}"

    command = expandvars(command, context)
    # We need to keep current environment variables
    # TODO-78: @alexanderilyin: merge this with features/steps/partcad-cli/commands/version.py
    env = dict(os.environ)
    if hasattr(context, "env"):
        env.update(context.env)
    if hasattr(context, "home_dir"):
        # Override the HOME variable
        env["HOME"] = context.home_dir

    # In case of Windows, we need to ensure that SYSTEMROOT and COMSPEC variables are set
    system_root = os.environ.get("SYSTEMROOT", "C:\\Windows")
    comspec = os.path.join(system_root, "System32", "cmd.exe")
    os.environ["SYSTEMROOT"] = system_root
    os.environ["SystemRoot"] = system_root
    os.environ["COMSPEC"] = comspec
    os.environ["ComSpeC"] = comspec

    cwd = None
    if hasattr(context, "test_dir"):
        cwd = context.test_dir

    # logging.debug(f"ENV: {env}")
    # TODO-79: @alexanderilyin: make multiline friendly
    logging.debug(f"Running command: {command} in {cwd}")

    start_time = time.time()
    # Run the command in the shell
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        encoding="utf-8",
    )
    end_time = time.time()
    context.duration = end_time - start_time

    logging.debug(f"Command output: {result.stdout}")
    logging.debug(f"Command error: {result.stderr}")
    logging.debug(f"Command return code: {result.returncode}")

    # Replace None with empty string
    if result.stdout is None:
        result.stdout = ""
    if result.stderr is None:
        result.stderr = ""

    # Store the result in the context for further steps
    context.result = result


@when("I run command")
def i_run_command_multiline(context: Context):
    # TODO-80: Document that it's better to have 'Uses' rather than 'Depends'
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
