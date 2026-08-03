#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="Show the current user configuration")
@click.pass_obj
def cli(cli_ctx) -> None:
    run(cli_ctx, "config.show", span_name="config")
