#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add has OBJECT NAME` -- a yes-or-no requirement: `has_<NAME>: true`, or `false` with `--not`.

    pc req add has bracket material                       # every solid in a material
    pc req add has bracket private_dependencies --not     # nothing it draws on is outside //pub

NAME is one of color, material, finish, weight (or mass), dependencies and
private_dependencies, with or without `has_`.
"""

import rich_click as click

from .... import object_kind
from ....requirement_args import (
    add,
    object_options,
    object_params,
    read_stdin,
    refuse_both,
    replace_option,
    stdin_options,
)


@click.command(
    help=(
        "Require OBJECT to have something -- NAME: color, material, finish, weight, dependencies or "
        "private_dependencies -- or, with '--not', not to. " + object_kind.LOOKED_UP
    )
)
@object_options
@replace_option
@stdin_options
@click.option("--not", "negated", is_flag=True, help="It must not have it: 'has_<NAME>: false'")
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, replace, from_stdin, as_json, negated, object, name):
    refuse_both(from_stdin, {"--not": negated})
    required = read_stdin(as_json) if from_stdin else not negated
    add(cli_ctx, object_params(package, assembly, scene, sketch, object), "has", name, required, replace)
