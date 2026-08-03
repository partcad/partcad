#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from .....service import run


@click.command(help="Set telemetry collection method")
@click.argument(
    "type",
    type=click.Choice(["none", "sentry"]),
    required=True,
    metavar="TYPE",
)
@click.pass_obj
def cli(cli_ctx, type: str) -> None:
    run(cli_ctx, "system.set.telemetry", {"key": "type", "value": type}, span_name="system set telemetry type")
