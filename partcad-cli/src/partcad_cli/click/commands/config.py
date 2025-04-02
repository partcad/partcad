#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ..cli_context import CliContext


@click.command(help="Show the current user configuration")
@click.pass_obj
def cli(cli_ctx: CliContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        # ctx: pc.Context = cli_ctx.get_partcad_context()

        for key, value in vars(pc.user_config).items():
            if not callable(value) and key[0] != "_":
                pc.logging.info(f"{key}: {value}")
        pc.logging.debug(f"File: {pc.user_config.get_config_dir()}")
