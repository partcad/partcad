from behave import *
from unittest.mock import patch
from click.testing import CliRunner
from contextlib import ExitStack

from partcad_cli.click.command import cli
import partcad.logging  as pc_logging

runner = CliRunner(mix_stderr=False)

@when("I run partcad healthcheck")
def step_impl(context):
    patches = []
    if hasattr(context, "mock_sys"):
        patches.append(patch("partcad.healthcheck.python_version.sys", context.mock_sys))
    if hasattr(context, "mock_winreg"):
        patches.append(patch("partcad.healthcheck.windows_registry.winreg", context.mock_winreg))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        context.result = runner.invoke(cli, ["healthcheck"])
        context.result.returncode = context.result.exit_code
        if context.result.returncode != 0:
            pc_logging.error(context.result.output)

@when("I run partcad healthcheck fix")
def step_impl(context):
    patches = []
    if hasattr(context, "mock_sys"):
        patches.append(patch("partcad.healthcheck.python_version.sys", context.mock_sys))
    if hasattr(context, "mock_winreg"):
        patches.append(patch("partcad.healthcheck.windows_registry.winreg", context.mock_winreg))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        context.result = runner.invoke(cli, ["healthcheck", "--fix"])
        context.result.returncode = context.result.exit_code
        if context.result.returncode != 0:
            pc_logging.error(context.result.output)
