#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from partcad_service_json_rpc import daemon


@click.command(help="Stop the PartCAD daemon serving this workspace")
def cli() -> None:
    if daemon.stop_daemon():
        click.echo("PartCAD daemon stopped")
    else:
        click.echo("No PartCAD daemon was running for this workspace")
