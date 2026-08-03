from behave import *
from typing import List
from unittest.mock import patch
from contextlib import ExitStack
from click.testing import CliRunner

from partcad_cli.click.command import cli
import partcad.logging  as pc_logging

# Capture stdout and stderr separately so the shared assertion steps in
# features/steps/partcad-cli/commands/version.py can read context.result.stderr
# (they log it for debugging) without click raising "stderr not separately
# captured".
#
# Click 8.2 removed the 'mix_stderr' argument and a Result now always exposes
# 'stdout' and 'stderr' separately, which is exactly what mix_stderr=False used
# to buy. On click < 8.2, however, the default is mix_stderr=True: stderr is
# folded into stdout and Result.stderr raises, so mix_stderr=False must be
# passed there. Construct the runner in a way that works on both.
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    # click >= 8.2 no longer accepts (or needs) mix_stderr.
    runner = CliRunner()

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
