#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad_cli as pcc
from ..service import run


@click.command(help="Display the versions of the PartCAD Python Module and CLI, then exit")
@click.pass_obj
def cli(cli_ctx) -> None:
    result = run(cli_ctx, "version", span_name="version")
    click.echo(f"PartCAD Python Module version: {result['partcad']}")
    click.echo(f"PartCAD CLI version: {pcc.__version__}")
