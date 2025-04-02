#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from partcad_cli.click.cli_context import CliContext


@click.command(help="Download and set up all imported packages")
@click.pass_obj
def cli(cli_ctx: CliContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        with pc.logging.Process("Install", "this"):
            ctx.user_config.force_update = True
            ctx.get_all_packages()
            if ctx.stats_git_ops:
                pc.logging.info(f"Git operations: {ctx.stats_git_ops}")
