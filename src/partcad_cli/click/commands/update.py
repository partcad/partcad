#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="Force update all imported packages to their latest versions. ")
@click.pass_obj
def cli(cli_ctx):
    run(cli_ctx, "update", span_name="update", needs_context=True)
