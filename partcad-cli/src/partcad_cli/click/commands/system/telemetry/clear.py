#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import os

import partcad as pc


@click.command(help="Clear telemetry data")
@click.pass_obj
def cli(cli_ctx) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysTelClear", "global"):
            id_path = os.path.join(pc.user_config.internal_state_dir, ".generated_id")
            if os.path.exists(id_path):
                os.unlink(id_path)
                pc.logging.info(f"Removed telemetry ID file: '{id_path}'")
            else:
                pc.logging.info(f"Telemetry ID file not found: '{id_path}'")
