#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click
from partcad_client import daemon


@click.command(help="Stop the PartCAD daemon serving this workspace")
def cli() -> None:
    if os.name == "nt":
        click.echo("The PartCAD socket daemon is not available on Windows yet; nothing to stop.")
        return
    if daemon.stop_daemon():
        click.echo("PartCAD daemon stopped")
    else:
        click.echo("No PartCAD daemon was running for this workspace")
