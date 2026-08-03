#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.command(help="Display the state of internal data used by PartCAD")
@click.pass_obj
def cli(cli_ctx) -> None:
    run(cli_ctx, "system.status", span_name="system status")
