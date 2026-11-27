#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev list [OBJECT]`: the revisions of a package, or the ones that changed an object.

What the IDE's Revisions tab lists down its left (`ops.rev.list`). A package --
no OBJECT, or one written as `//pkg` -- lists every commit that changed its
directory, a page at a time; an object, only the commits that changed it (its
declaration, or a file it is built from), each with how.
"""

import rich_click as click

from ....operations_args import echo_json, print_revisions, run_subject, target_options
from ....parameters import param_option, param_params


@click.command(
    help=(
        "List the revisions of the package -P selects -- every commit that changed it, newest first, '*' marking "
        "the one checked out -- or, with OBJECT, only the ones that changed OBJECT itself, each with how. "
        "--limit and --after page through a long history."
    )
)
@target_options
@click.option("--limit", type=click.IntRange(min=1), default=100, show_default=True, help="How many to list")
@click.option("--after", type=str, default=None, help="List the ones after this commit: where the last page ended")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, limit, after, as_json, params, object):
    extra = {"limit": limit, **({"after": after} if after else {}), **param_params(params)}
    result = run_subject(cli_ctx, "ops.rev.list", (package, interface, assembly, scene, sketch, object), extra)
    if as_json:
        echo_json(result)
    else:
        print_revisions(result)
