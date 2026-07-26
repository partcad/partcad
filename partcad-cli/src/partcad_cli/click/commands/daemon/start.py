#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from partcad_service_json_rpc import client


@click.command(help="Start the PartCAD daemon for this workspace (if needed) and print its socket path")
def cli() -> None:
    path = client.start_daemon()
    click.echo(path)
