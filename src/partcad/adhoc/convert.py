#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Converting a CAD or sketch file that belongs to no package.

File in, file out: the input is wrapped in a throwaway package (see `adhoc.py`)
and written back out as another format. Nothing is added to any package - that
is `pc convert`, which also rewrites the object's definition, and `pc export`,
which writes a file for an object a package already declares.

The 2D projections are the sibling module, `render.py`: a picture of a shape is
not another way of storing it, and `pc adhoc convert` deliberately does not
write one.
"""

from .adhoc import (  # noqa: F401  (re-exported: the historical import path)
    PACKAGE_ONLY_TYPES,
    generate_partcad_config,
    reject_package_only,
    write_output_file,
)


def convert_cad_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """
    Convert a CAD file from one format to another.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file.
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file.
    """
    reject_package_only(input_type, output_type)
    write_output_file(input_filename, input_type, output_filename, output_type, kind="part", verb="Convert")


def convert_sketch_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """
    Convert a sketch file from one format to another using an adhoc PartCAD context.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file (e.g., svg, dxf).
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file (e.g., svg, dxf).
    """
    write_output_file(input_filename, input_type, output_filename, output_type, kind="sketch", verb="Convert")


def convert_scene_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """Convert a scene file from one format to another using an ad-hoc context.

    The same file-in, file-out operation as the two above, for the third kind of
    object a file can hold. `pc open --with mujoco` is what asks for it: MuJoCo
    reads MJCF and nothing else, so a Gazebo world it is pointed at is written
    out as MJCF first -- which is CAD work, and so is the daemon's.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file (e.g. world, mjcf).
        output_filename: Path to save the output file.
        output_type: Format of the output file.
    """
    reject_package_only(
        input_type,
        output_type,
        advice="Use 'pc export' on the scene in its package instead.",
    )
    write_output_file(input_filename, input_type, output_filename, output_type, kind="scene", verb="Convert")
