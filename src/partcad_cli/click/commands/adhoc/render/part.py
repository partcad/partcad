#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ....service import run
from ....viewport import viewport_options, viewport_params

# The part types a projection can be made of - the same list 'adhoc/convert/part.py'
# reads, and inlined for the same reason (the thin CLI must not import the heavy
# partcad package). Every one of them is an *input* here: unlike a conversion,
# what comes out is not a part type at all.
PART_TYPES = [
    "step",
    "brep",
    "stl",
    "3mf",
    "threejs",
    "obj",
    "iges",
    "gltf",
    "cadquery",
    "build123d",
    "chili3d",
    "sdf",
    "scad",
]

# The 2D projections '//builtin/render' implements (partcad.shape's
# RENDER_EXTENSION_MAPPING, and partcad.adhoc.render's PART_RENDER_FORMATS).
# A file type a package implements itself is not offered: it is declared in that
# package, and an ad-hoc render has no package.
RENDER_TYPES = ["svg", "png", "jpeg", "dxf"]


@click.command(help="Render a CAD file to a 2D image (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(PART_TYPES),
    help="Input file type. Inferred from filename if not provided.",
)
@click.option(
    "--output",
    "output_type",
    type=click.Choice(RENDER_TYPES),
    help="The projection to write. Inferred from the output filename if not provided.",
)
@viewport_options
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(cli_ctx, input_type, output_type, view, viewport_origin, viewport_up, input_filename, output_filename):
    """Render a CAD file to a 2D image without modifying project configuration."""
    run(
        cli_ctx,
        "adhoc.render",
        {
            "kind": "part",
            "input_type": input_type,
            "output_type": output_type,
            # Absolute so the daemon reads/writes in the user's cwd.
            "input_filename": os.path.abspath(input_filename),
            "output_filename": os.path.abspath(output_filename) if output_filename else None,
            **viewport_params(view, viewport_origin, viewport_up),
        },
        needs_context=False,
    )
