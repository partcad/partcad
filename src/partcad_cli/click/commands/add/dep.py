#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""`pc add dep NAME LOCATION`: what `pc ops deps add` is called now, kept so that it goes on working.

Hidden from the help: the command to learn is `pc ops deps add`, which this says
before doing exactly what it does.
"""

import rich_click as click

from ..ops.deps.add import add


@click.command(
    hidden=True,
    help="Add a dependency: 'pc ops deps add' by its old name.",
)
@click.argument("alias", type=str)
@click.argument("location", type=str)
@click.option(
    "--track",
    type=str,
    default=None,
    help="The branch of a git dependency to track. Defaults to the one the repository calls its default.",
)
@click.pass_context
def cli(click_ctx: click.Context, alias: str, location: str, track: str):
    click.echo("'pc add dep' is 'pc ops deps add' now", err=True)
    add(click_ctx.obj, click_ctx.parent.params.get("package") or "", alias, location, track)
