#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops list [OBJECT]`: the commits that changed a package, newest first.

What the IDE's Revisions tab lists down its left. Of the package OBJECT is in,
or of the package `-P` selects when no OBJECT is given; a package that shares
its repository with others lists the commits that changed its own directory.
"""

import rich_click as click

from ...operations_args import echo_json, print_revisions, target_options, target_params
from ...parameters import param_option, param_params
from ...service import run


@click.command(
    help=(
        "List the commits that changed the package of OBJECT -- or, with no OBJECT, the package -P selects -- "
        "newest first, '*' marking the one checked out. A package in no git repository, or with nothing "
        "committed, is not published yet."
    )
)
@target_options
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, as_json, params, object):
    result = run(
        cli_ctx,
        "revisions.list",
        {**target_params(package, interface, assembly, scene, sketch, object), **param_params(params)},
        needs_context=True,
    )
    if result is None:
        raise click.ClickException("Nothing was listed")
    if as_json:
        echo_json(result)
    else:
        print_revisions(result)
