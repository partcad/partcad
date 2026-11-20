#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req remove feature` -- take a feature out of an object's requirements."""

import rich_click as click

from .... import object_kind
from ....requirement_args import object_options, object_params, remove


@click.command(
    help="Remove a feature from OBJECT's requirements: NAME. One that a simulation or an analysis scenario names is refused, unless '--with-references' takes it out of those as well. "
    + object_kind.LOOKED_UP
)
@object_options
@click.option(
    "--with-references",
    is_flag=True,
    help="Also take the feature out of every simulation and analysis scenario that names it (their 'feature:')",
)
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, with_references, object, name):
    remove(
        cli_ctx,
        object_params(package, assembly, scene, sketch, object),
        "feature",
        name,
        with_references=with_references,
    )
