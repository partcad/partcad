#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from partcad_client import daemon


@click.command(help="Stop the PartCAD daemon serving this workspace")
def cli() -> None:
    # `stop_daemon` knows both transports -- the AF_UNIX socket and the Windows
    # named pipe -- so there is nothing to decide here. It answered Windows with
    # "nothing to stop" while `pc daemon start` was starting one.
    if daemon.stop_daemon():
        click.echo("PartCAD daemon stopped")
    else:
        click.echo("No PartCAD daemon was running for this workspace")
