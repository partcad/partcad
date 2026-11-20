#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req remove match` -- take matching another object out of an object's requirements."""

import rich_click as click

from .... import object_kind
from ....requirement_args import object_options, object_params, remove


@click.command(
    help="Remove matching another object from OBJECT's requirements: OTHER, or only the amounts the flags name. "
    + object_kind.LOOKED_UP
)
@object_options
@click.option("--volume", is_flag=True, help="Only its volume")
@click.option("--displacement", is_flag=True, help="Only its displacement")
@click.option("--mass", "--weight", "mass", is_flag=True, help="Only its mass")
@click.argument("object", type=str)
@click.argument("other", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, volume, displacement, mass, object, other):
    remove(
        cli_ctx,
        object_params(package, assembly, scene, sketch, object),
        "match",
        other,
        amounts=[
            amount for amount, chosen in (("volume", volume), ("displacement", displacement), ("mass", mass)) if chosen
        ],
    )
