#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_client import object_types

from ....service import run

# PartCAD part types (partcad.shape.PART_EXTENSION_MAPPING keys), inlined so the
# thin CLI does not import the heavy partcad package. 'urdf' is deliberately
# absent: it describes an assembly, not a shape, and only means anything inside
# a package - see partcad.adhoc.convert.PACKAGE_ONLY_TYPES and
# 'pc convert assembly'. It is still inferable from a '.urdf' filename, which is
# where that rejection is reported from.
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
# And the native CAD formats PartCAD ships as declarations rather than factories
# (see `partcad_client.object_types`), read through cadmpeg.
PART_TYPES += [part_type for part_type in object_types.BUILTIN_PART_TYPE_EXTENSION if part_type not in PART_TYPES]

# What PartCAD can write. The rest are input formats only: PartCAD reads a
# Chili3D, SDF or OpenSCAD script and has no exporter that produces one (see
# partcad.shape.UNEXPORTABLE_PART_TYPES, inlined here for the same reason - it
# also holds 'urdf', which is absent from the list above for the reason given
# there).
INPUT_ONLY_PART_TYPES = ["chili3d", "sdf", "scad"] + [
    part_type
    for part_type in object_types.BUILTIN_PART_TYPE_EXTENSION
    if part_type not in object_types.WRITABLE_PART_TYPES
]
OUTPUT_PART_TYPES = [part_type for part_type in PART_TYPES if part_type not in INPUT_ONLY_PART_TYPES]


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
    type=click.Choice(OUTPUT_PART_TYPES),
    help="Output file type. Inferred from filename if not provided.",
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(cli_ctx, input_type, output_type, input_filename, output_filename):
    """Convert CAD files from one format to another without modifying project configuration."""
    if input_type is None:
        # The daemon infers a type from the extensions its factories write; a
        # format PartCAD reads through a declaration is named here, where the
        # client's table of them is ('.FCStd', '.SLDPRT', '.igs' ...).
        detected = object_types.type_of_file(input_filename)
        if detected in object_types.BUILTIN_PART_TYPE_EXTENSION:
            input_type = detected
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
