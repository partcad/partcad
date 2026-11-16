#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req remove interface` -- take an interface out of an object's requirements."""

import rich_click as click

from .... import object_kind
from ....requirement_args import object_options, object_params, remove


@click.command(
    help="Remove an interface from OBJECT's requirements: INTERFACE, or only the instances '--instance' names. "
    + object_kind.LOOKED_UP
)
@object_options
@click.option("--instance", "instances", multiple=True, help="Remove only this instance of it's requirement")
@click.argument("object", type=str)
@click.argument("interface", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, instances, object, interface):
    remove(
        cli_ctx,
        object_params(package, assembly, scene, sketch, object),
        "interface",
        interface,
        instances=list(instances),
    )
