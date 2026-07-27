#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


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
def cli(cli_ctx, filters: str, fix: bool, dry_run: bool) -> None:
    run(
        cli_ctx,
        "healthcheck",
        {"filters": filters, "fix": fix, "dry_run": dry_run},
        span_name="healthcheck",
    )
