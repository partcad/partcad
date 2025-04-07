#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ..cli_context import CliContext


@click.command(help="Perform a health check of the host system to identify known issues.")
@click.option(
    "--filters",
    help="Run only tests with the specified tag(s), comma separated",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List supported healthcheck tests",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Attempt to fix any issues found",
)
@click.pass_obj
def cli(cli_ctx: CliContext, filters: str, fix: bool, dry_run: bool) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        pc.healthcheck.tests.run_tests(filters=filters, fix=fix, dry_run=dry_run)
