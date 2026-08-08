#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ....service import run

# PartCAD part types (partcad.shape.PART_EXTENSION_MAPPING keys), inlined so the
# thin CLI does not import the heavy partcad package.
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


@click.command(help="Convert CAD files between formats (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(PART_TYPES),
    help="Input file type. Inferred from filename if not provided.",
)
@click.option(
    "--output",
    "output_type",
    type=click.Choice(PART_TYPES),
    help="Output file type. Inferred from filename if not provided.",
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(cli_ctx, input_type, output_type, input_filename, output_filename):
    """Convert CAD files from one format to another without modifying project configuration."""
    run(
        cli_ctx,
        "adhoc.convert",
        {
            "kind": "part",
            "input_type": input_type,
            "output_type": output_type,
            # Absolute so the daemon reads/writes in the user's cwd.
            "input_filename": os.path.abspath(input_filename),
            "output_filename": os.path.abspath(output_filename) if output_filename else None,
        },
        needs_context=False,
    )
