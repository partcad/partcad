#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""`pc update`: what `pc ops deps update --all` is called now, kept so that it goes on working.

Hidden from the help: the command to learn is `pc ops deps update`, which this
says before doing what it always did -- every tracked dependency of the
workspace moved to the tip of its branch, then every import fetched again.
"""

import rich_click as click

from .ops.deps.update import update


@click.command(
    hidden=True,
    help="Move every tracked dependency to the newest commit of its branch: 'pc ops deps update --all'.",
)
@click.pass_obj
def cli(cli_ctx):
    click.echo("'pc update' is 'pc ops deps update --all' now", err=True)
    result = update(cli_ctx, None, (), True)
    click.echo("Successfully updated %d packages" % (result.get("count") or 0))
