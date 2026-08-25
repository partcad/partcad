#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
import partcad.actions.config as pc_actions_config


@click.command(help="Set the Sentry DSN")
@click.argument(
    "dsn",
    metavar="DSN",
    required=True,
)
@click.pass_obj
def cli(cli_ctx, dsn: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysSetTelDsn", "global"):
            yaml, config = pc_actions_config.system_config_get()
            if not "telemetry" in config:
                config["telemetry"] = {}

            config["telemetry"]["sentryDsn"] = dsn
            pc.logging.info("Sentry DSN set to %s", dsn)

            pc_actions_config.system_config_set(yaml, config)
