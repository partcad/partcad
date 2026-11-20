#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req remove has` -- take a yes-or-no requirement out of an object's requirements."""

import rich_click as click

from .... import object_kind
from ....requirement_args import object_options, object_params, remove


@click.command(
    help="Remove a yes-or-no requirement from OBJECT's requirements: has_NAME, whichever of its spellings it is written with. "
    + object_kind.LOOKED_UP
)
@object_options
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, object, name):
    remove(cli_ctx, object_params(package, assembly, scene, sketch, object), "has", name)
