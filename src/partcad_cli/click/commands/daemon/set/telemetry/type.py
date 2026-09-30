#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from .....service import run


@click.command(help="Set the telemetry collection method of the daemon")
@click.argument("type", type=click.Choice(["none", "sentry"]), required=True, metavar="TYPE")
@click.pass_obj
def cli(cli_ctx, type: str) -> None:
    run(cli_ctx, "daemon.set.telemetry", {"key": "type", "value": type}, span_name="daemon set telemetry type")
