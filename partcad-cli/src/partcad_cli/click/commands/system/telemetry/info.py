#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import os

import partcad as pc


@click.command(help="Get telemetry information")
@click.pass_obj
def cli(cli_ctx) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysTelInfo", "global"):
            # The ID is generated and stored by telemetry_sentry.py under the
            # user config directory, not under 'internalStateDir'. Looking
            # anywhere else reports "None" for a user who has one.
            id_path = os.path.join(pc.user_config.get_config_dir(), ".generated_id")
            if os.path.exists(id_path):
                with open(id_path, "r") as file:
                    id_value = file.read()
                    pc.logging.info(f"Telemetry ID: '{id_value}'")
            else:
                pc.logging.info(f"Telemetry ID: None")
        pc.logging.info(f"Telemetry type: '{pc.user_config.telemetry_config.type}'")
        pc.logging.info(f"Telemetry env: '{pc.user_config.telemetry_config.env}'")
