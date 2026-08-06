#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from .....service import run


@click.command(help="Set the environment the daemon's telemetry is collected for")
@click.argument("env", type=click.Choice(["dev", "test", "prod"]), metavar="ENV", required=True)
@click.pass_obj
def cli(cli_ctx, env: str) -> None:
    run(cli_ctx, "daemon.set.telemetry", {"key": "env", "value": env}, span_name="daemon set telemetry env")
