#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
import partcad.actions.config as pc_actions_config


@click.command(help="Set telemetry collection method")
@click.argument(
    "type",
    type=click.Choice(["none", "sentry"]),
    required=True,
    metavar="TYPE",
)
@click.pass_obj
def cli(cli_ctx, type: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysSetTelType", "global"):
            yaml, config = pc_actions_config.system_config_get()
            if not "telemetry" in config:
                config["telemetry"] = {}

            if type == "none":
                config["telemetry"]["type"] = "none"
                pc.logging.info("Telemetry collection disabled")
            elif type == "sentry":
                config["telemetry"]["type"] = "sentry"
                pc.logging.info("Telemetry collection enabled with Sentry")
            else:
                pc.logging.error(f"Unknown telemetry type: {type}")
                return

            pc_actions_config.system_config_set(yaml, config)
