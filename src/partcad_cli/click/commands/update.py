#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="""Move every tracked dependency to the newest commit of its branch.

    Each git dependency with 'track: <branch>' in this workspace's packages gets
    its 'revision:' in 'partcad.yaml' rewritten to the commit that branch is at
    now, and every imported package is then fetched again. Loading a package
    never moves a dependency it has downloaded before; this is what does.""")
@click.pass_obj
def cli(cli_ctx):
    run(cli_ctx, "update", span_name="update", needs_context=True)
