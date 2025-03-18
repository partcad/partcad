from behave import *
from typing import List
from unittest.mock import patch
from contextlib import ExitStack
from click.testing import CliRunner

from partcad_cli.click.command import cli
import partcad.logging  as pc_logging

runner = CliRunner(mix_stderr=False)

def healthcheck_cli(context, options: List[str] = []):
    patches = []
    if hasattr(context, "mock_sys"):
        patches.append(patch("partcad.healthcheck.python_version.sys", context.mock_sys))
    if hasattr(context, "mock_winreg"):
        patches.append(patch("partcad.healthcheck.windows_registry.winreg", context.mock_winreg))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        context.result = runner.invoke(cli, ["healthcheck"] + options)
        context.result.returncode = context.result.exit_code
        if context.result.returncode != 0:
            pc_logging.error(context.result.output)

@when("I run partcad healthcheck")
def step_impl(context):
    healthcheck_cli(context)

@when(u'I run partcad healthcheck with options "{options}"')
def step_impl(context, options: str):
    healthcheck_cli(context, options.split())
