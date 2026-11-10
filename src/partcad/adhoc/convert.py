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

# The assembly formats that mean something outside a package when they are
# read only to be written as their compound: a URDF's meshes are found beside
# it, and its links are parts of the throwaway package for as long as it lasts.
# An ASSY is still refused: it is nothing but references to a package's parts.
COMPOUND_INPUT_TYPES = ("urdf",)


def convert_cad_file(
    input_filename: str, input_type: str, output_filename: str, output_type: str, compound: bool = False
) -> None:
    """
    Convert a CAD file from one format to another.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file.
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file.
        compound (bool): Read the input as the assembly it holds - one of the
            assembly types, a URDF included - and write it as its compound,
            one part (see 'partcad.assembly_compound'), rather than read it as
            a part.
    """
    if compound:
        reject_package_only(
            None if (input_type or "").lower() in COMPOUND_INPUT_TYPES else input_type,
            output_type,
            advice="Use 'pc export --compound' on the assembly in its package instead.",
        )
        write_output_file(
            input_filename, input_type, output_filename, output_type, kind="assembly", verb="Convert", compound=True
        )
        return
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
    object a file can hold.

    Nothing asks for it today, and that is worth stating rather than leaving to
    be discovered. The scene formats that are not `assy` all belong to a
    simulation engine's plugin package, and a throwaway package has no dependency
    on one -- so `pc ide open --with mujoco` refuses a file that is not already MJCF
    instead of converting it (see `partcad_client.external._transcode_scene`).
    This stays because the machinery is the part conversion's, not because there
    is a caller: a scene format PartCAD itself implemented would convert here.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file (e.g. assy).
        output_filename: Path to save the output file.
        output_type: Format of the output file.
    """
    reject_package_only(
        input_type,
        output_type,
        advice="Use 'pc export' on the scene in its package instead.",
    )
    write_output_file(input_filename, input_type, output_filename, output_type, kind="scene", verb="Convert")
