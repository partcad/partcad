#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from .....service import run


@click.command(help="Set the Sentry DSN of the daemon")
@click.argument("dsn", metavar="DSN", required=True)
@click.pass_obj
def cli(cli_ctx, dsn: str) -> None:
    run(cli_ctx, "daemon.set.telemetry", {"key": "sentryDsn", "value": dsn}, span_name="daemon set telemetry sentryDsn")
