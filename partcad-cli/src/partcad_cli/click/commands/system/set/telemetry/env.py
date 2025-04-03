#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
import partcad.actions.config as pc_actions_config


@click.command(help="Set the environment the telemetry is collected for")
@click.argument(
    "env",
    type=click.Choice(["dev", "test", "prod"]),
    metavar="ENV",
    required=True,
)
@click.pass_obj
def cli(cli_ctx, env: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysSetTelEnv", "global"):
            yaml, config = pc_actions_config.system_config_get()
            if not "telemetry" in config:
                config["telemetry"] = {}

            config["telemetry"]["env"] = env
            pc.logging.info("Telemetry environment set to %s", env)

            pc_actions_config.system_config_set(yaml, config)
