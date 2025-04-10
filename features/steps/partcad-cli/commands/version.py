from behave import given, when, then
from behave.runner import Context
import logging
from features.utils import expandvars
from strip_ansi import strip_ansi


def normalize_path(text: str) -> str:
    return text.replace("\\", "/").replace("//", "/")


@then('command takes less than "{max_duration}" seconds')
def step_impl(context, max_duration):
    assert context.duration < float(max_duration)


@then("STDOUT should contain '{substring}' with path")
@then('STDOUT should contain "{substring}" with path')
def step_impl(context, substring):
    # TODO-72: @alexanderilyin: refactor & unify all output matching related steps
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {strip_ansi(context.result.stderr)}")
    logging.debug(f"STDOUT: {strip_ansi(context.result.stdout)}")
    if normalize_path(substring) not in normalize_path(strip_ansi(context.result.stdout)):
        raise AssertionError(
            f"Expected '{normalize_path(substring)}' in '{normalize_path(strip_ansi(context.result.stdout))}', but it was not found"
        )


@then("STDOUT should contain '{substring}'")
@then('STDOUT should contain "{substring}"')
def step_impl(context, substring):
    # TODO-72: @alexanderilyin: refactor & unify all output matching related steps
    substring = expandvars(substring, context)
    logging.info(f"STDERR: {strip_ansi(context.result.stderr)}")
    logging.info(f"STDOUT: {strip_ansi(context.result.stdout)}")
    if substring not in strip_ansi(context.result.stdout):
        raise AssertionError(f"Expected '{substring}' in STDOUT, but it was not found")


@then("STDERR should contain '{substring}' with path")
@then('STDERR should contain "{substring}" with path')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-73: @alexanderilyin: strip ASCII color codes from the output
    if normalize_path(substring) not in normalize_path(strip_ansi(context.result.stderr)):
        raise AssertionError(
            f"Expected '{normalize_path(substring)}' in '{normalize_path(strip_ansi(context.result.stderr))}', but it was not found"
        )


@then("STDERR should contain '{substring}'")
@then('STDERR should contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-73: @alexanderilyin: strip ASCII color codes from the output
    if substring not in strip_ansi(context.result.stderr):
        raise AssertionError(f"Expected '{substring}' in STDERR, but it was not found")


@then('STDOUT should not contain "{substring}" with path')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-74: @alexanderilyin: strip ASCII color codes from the output
    if normalize_path(substring) in normalize_path(strip_ansi(context.result.stdout)):
        raise AssertionError(
            f"Expected '{normalize_path(substring)}' not to be in '{normalize_path(strip_ansi(context.result.stdout))}', but it was found"
        )


@then('STDOUT should not contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-74: @alexanderilyin: strip ASCII color codes from the output
    if substring in context.result.stdout:
        raise AssertionError(f"Expected '{substring}' not to be in STDOUT, but it was found")


@then('STDERR should not contain "{substring}" with path')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-75: @alexanderilyin: strip ASCII color codes from the output
    if normalize_path(substring) in normalize_path(strip_ansi(context.result.stderr)):
        raise AssertionError(
            f"Expected '{normalize_path(substring)}' not to be in '{normalize_path(strip_ansi(context.result.stderr))}', but it was found"
        )


@then('STDERR should not contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {context.result.stderr}")
    logging.debug(f"STDOUT: {context.result.stdout}")
    # TODO-75: @alexanderilyin: strip ASCII color codes from the output
    if substring in context.result.stderr:
        raise AssertionError(f"Expected '{substring}' not to be in STDERR, but it was found")


@then('the command should exit with a status code of "{exit_code}"')
def step_impl(context, exit_code):
    assert context.result.returncode == int(exit_code)


@then("the command should exit with a non-zero status code")
def step_impl(context):
    assert context.result.returncode != 0


@then("CLI version matches package version")
def step_impl(context: Context) -> None:
    import subprocess
    import partcad

    import shutil

    partcad_path = shutil.which("partcad")
    if not partcad_path:
        raise RuntimeError("partcad executable not found in PATH")
    cli_version = subprocess.check_output([partcad_path, "version"], stderr=subprocess.STDOUT).decode()
    package_version = partcad.__version__

    assert package_version in cli_version, (
        f"CLI version ({cli_version}) doesn't match " f"package version ({package_version})"
    )


@then("the following messages should not be present")
def step_impl(context):
    messages = context.text.strip().split("\n")
    for stream in ["stdout", "stderr"]:
        output = getattr(context.result, stream)
        for message in messages:
            assert message not in output, f"Message '{message}' found in {stream}"
