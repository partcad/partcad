#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="Download and set up all imported packages")
@click.pass_obj
def cli(cli_ctx) -> None:
    run(cli_ctx, "install", span_name="install", needs_context=True)
