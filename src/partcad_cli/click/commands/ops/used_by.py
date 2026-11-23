#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops used-by [OBJECT]`: what among the loaded packages uses an object, or a package.

The IDE's Operations > Used By tab: every object the daemon has loaded that
refers to OBJECT -- or, with no OBJECT, to anything in the package `-P` selects
-- with how many times; an assembly that places a bolt four times uses it four
times. Only what is loaded is looked at, which the command says when it finds
nothing, so that an empty answer is not read as "nothing uses it anywhere".
`--load` loads every package below the root first (`pc list` loads them too),
which is what makes the answer about the whole workspace.
"""

import rich_click as click

from ...operations_args import echo_json, print_used_by, target_options, target_params
from ...parameters import param_option, param_params
from ...service import run


@click.command(
    help=(
        "List the objects PartCAD has loaded that use OBJECT -- or, with no OBJECT, anything in the package -P "
        "selects -- each with how many times. Only what is loaded is looked at: --load loads every package of "
        "the workspace first."
    )
)
@target_options
@click.option("--load", is_flag=True, help="Load every package below the root first, so that all of them are asked")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, load, as_json, params, object):
    request = {**target_params(package, interface, assembly, scene, sketch, object), **param_params(params)}
    request["load"] = load
    result = run(cli_ctx, "usage.used_by", request, needs_context=True)
    if result is None:
        raise click.ClickException("Nothing was listed")
    if as_json:
        echo_json(result)
    else:
        print_used_by(result, result.get("object") or object or "it")
