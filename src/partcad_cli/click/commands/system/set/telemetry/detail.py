#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
import partcad.actions.config as pc_actions_config


@click.command(help="Set how deep telemetry traces go")
@click.argument(
    "detail",
    type=click.Choice([pc.telemetry.DETAIL_ACTIONS, pc.telemetry.DETAIL_METHODS]),
    required=True,
    metavar="DETAIL",
)
@click.pass_obj
def cli(cli_ctx, detail: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysSetTelDetail", "global"):
            yaml, config = pc_actions_config.system_config_get()
            if "telemetry" not in config:
                config["telemetry"] = {}

            config["telemetry"]["detail"] = detail
            if detail == pc.telemetry.DETAIL_ACTIONS:
                pc.logging.info("Telemetry reports the operations PartCAD names, and nothing below them")
            else:
                pc.logging.info("Telemetry also reports a span per instrumented method")

            pc_actions_config.system_config_set(yaml, config)
