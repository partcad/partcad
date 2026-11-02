#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_client import object_types

from .... import render_options
from ....service import run
from ....viewport import viewport_options, viewport_params
from ..convert.part import PART_TYPES

# 'PART_TYPES' is the part types a projection can be made of - the list
# 'adhoc/convert/part.py' reads, inlined there for the reason it gives (the thin
# CLI must not import the heavy partcad package). Every one of them is an
# *input* here: unlike a conversion, what comes out is not a part type at all.

# The 2D projections '//builtin/render' implements (partcad.shape's
# RENDER_EXTENSION_MAPPING, and partcad.adhoc.render's PART_RENDER_FORMATS).
# A file type a package implements itself is written by naming that package with
# '-e'; which types it declares is the daemon's to check, once it has read it.
RENDER_TYPES = ["svg", "png", "jpeg", "dxf"]


@click.command(help="Render a CAD file to a 2D image (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(PART_TYPES),
    help="Input file type. Inferred from filename if not provided.",
)
@render_options.output_option(RENDER_TYPES)
@render_options.adhoc_options
@viewport_options
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(
    cli_ctx,
    input_type,
    output_type,
    output_dir,
    options_package,
    params,
    reproducible,
    view,
    viewport_origin,
    viewport_up,
    input_filename,
    output_filename,
):
    """Render a CAD file to a 2D image without modifying project configuration."""
    if input_type is None:
        # Named here for the reason 'adhoc convert' names it (see there).
        detected = object_types.type_of_file(input_filename)
        if detected in object_types.BUILTIN_PART_TYPE_EXTENSION:
            input_type = detected
    run(
        cli_ctx,
        "adhoc.render",
        {
            "kind": "part",
            "input_type": input_type,
            # Absolute so the daemon reads/writes in the user's cwd.
            "input_filename": os.path.abspath(input_filename),
            "output_filename": os.path.abspath(output_filename) if output_filename else None,
            **render_options.adhoc_params(
                output_type, RENDER_TYPES, output_dir, options_package, params, reproducible, output_filename
            ),
            **viewport_params(view, viewport_origin, viewport_up),
        },
        needs_context=False,
    )
