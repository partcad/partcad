#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click
from partcad_service_json_rpc import client


@click.command(help="Start the PartCAD daemon for this workspace (if needed) and print its socket path")
def cli() -> None:
    if os.name == "nt":
        click.echo(
            "The PartCAD socket daemon is not available on Windows yet; "
            "commands run a per-invocation service instead."
        )
        return
    path = client.start_daemon()
    click.echo(path)
