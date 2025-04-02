#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
import partcad_cli as pcc


@click.command(help="Display the versions of the PartCAD Python Module and CLI, then exit")
@click.pass_obj
def cli(cli_ctx) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.telemetry.start_as_current_span("version"):
            pc.logging.info(f"PartCAD Python Module version: {pc.__version__}")
            pc.logging.info(f"PartCAD CLI version: {pcc.__version__}")
