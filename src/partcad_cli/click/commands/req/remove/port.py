#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req remove port` -- take a port out of an object's requirements."""

import rich_click as click

from .... import object_kind
from ....requirement_args import object_options, object_params, remove


@click.command(help="Remove a port from OBJECT's requirements: the one called NAME. " + object_kind.LOOKED_UP)
@object_options
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, object, name):
    remove(cli_ctx, object_params(package, assembly, scene, sketch, object), "port", name)
