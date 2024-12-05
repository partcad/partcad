from behave import given, when, then
from behave.runner import Context
import logging
from features.utils import expandvars
from strip_ansi import strip_ansi


@then('command takes less than "{max_duration}" seconds')
def step_impl(context, max_duration):
    assert context.duration < float(max_duration)


@then('STDOUT should contain "{substring}"')
def step_impl(context, substring):
    # TODO: @alexanderilyin: refactor & unify all output matching related steps
    substring = expandvars(substring, context)
    logging.debug(f"STDERR: {strip_ansi(context.result.stderr)}")
    logging.debug(f"STDOUT: {strip_ansi(context.result.stdout)}")
    assert substring in strip_ansi(context.result.stdout)


@then('STDERR should contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug("STDERR: " + context.result.stderr)
    logging.debug("STDOUT: " + context.result.stdout)
    # TODO: @alexanderilyin: strip ASCII color codes from the output
    assert substring in strip_ansi(context.result.stderr)


@then('STDOUT should not contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug("STDERR: " + context.result.stderr)
    logging.debug("STDOUT: " + context.result.stdout)
    # TODO: @alexanderilyin: strip ASCII color codes from the output
    assert substring not in context.result.stdout


@then('STDERR should not contain "{substring}"')
def step_impl(context, substring):
    substring = expandvars(substring, context)
    logging.debug("STDERR: " + context.result.stderr)
    logging.debug("STDOUT: " + context.result.stdout)
    # TODO: @alexanderilyin: strip ASCII color codes from the output
    assert substring not in context.result.stderr


@then('the command should exit with a status code of "{exit_code}"')
def step_impl(context, exit_code):
    assert context.result.returncode == int(exit_code)


@then("CLI version matches package version")
def step_impl(context: Context) -> None:
    import subprocess
    import partcad

    cli_version = subprocess.check_output(["partcad", "version"], stderr=subprocess.STDOUT).decode()
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
