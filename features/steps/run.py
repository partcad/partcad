from behave import when, given
from behave.runner import Context
import time
import logging
import os
import subprocess
from features.pristine_env import PYTHON_ENV  # type: ignore
from features.utils import expandvars  # type: ignore # TODO: @alexanderilyin python.autoComplete.extraPaths


def run(context: Context, command: str):
    # Each scenario shells out to the CLI, often several times. Wrapping every
    # invocation in `coverage run` imports coverage.py and enables line tracing
    # on each fresh subprocess, which is a large share of behave's runtime.
    # Only pay that cost when coverage is actually being collected
    # (PC_BEHAVE_COVERAGE=1, set on the single CI cell that reports coverage);
    # otherwise -- local runs and every other CI cell -- invoke the CLI
    # directly. The scenarios that run are identical either way.
    collect_coverage = os.environ.get("PC_BEHAVE_COVERAGE", "") not in ("", "0", "false", "False")
    for prefix in ("pc ", "partcad "):
        if command.startswith(prefix):
            cli_args = command[len(prefix) :]
            if collect_coverage:
                command = (
                    "coverage run --rcfile=$PARTCAD_ROOT/dev-tools/coverage.rc "
                    f"--data-file=$PARTCAD_ROOT/.coverage --parallel -m partcad_cli.click.command {cli_args}"
                )
            else:
                command = f"python -m partcad_cli.click.command {cli_args}"
            break

    command = expandvars(command, context)
    # We need to keep current environment variables
    # TODO-78: @alexanderilyin: merge this with features/steps/partcad-cli/commands/version.py
    env = dict(os.environ)
    # Importing partcad swept the PYTHON* variables out of this process; the CLI
    # is not a sandbox interpreter and still wants the ones CI exported for it.
    env.update(PYTHON_ENV)
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
        errors="replace",
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
