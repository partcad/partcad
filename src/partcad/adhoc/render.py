#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Rendering a CAD or sketch file that belongs to no package.

The counterpart of `convert.py` for the other thing an output file can be. A
conversion writes geometry another CAD tool goes on working with; a render
writes a 2D projection to look at, and that is where a viewing angle means
anything - so this is the one of the two that takes a viewport.

The mechanism is the same throwaway package (`common.py`), which is why
`pc adhoc render` can aim a projection the way `pc render` does even though
there is no `partcad.yaml` to configure it in: the viewport arrives as an export
parameter, on top of what the built-in implementation would otherwise default
to.
"""

from .adhoc import reject_package_only, write_output_file

# The 2D projections '//builtin/render' implements, which are the only ones an
# ad-hoc render can write: a file type a package implements itself is declared
# in that package, and here there is no package to declare it in.
PART_RENDER_FORMATS = ["svg", "png", "jpeg", "dxf"]

# The same, for a sketch. A sketch is already flat, so all four mean something
# for one too - and 'dxf' more than for a part, since a drawing is what a sketch
# is for.
SKETCH_RENDER_FORMATS = ["svg", "png", "jpeg", "dxf"]

_ADVICE = "Declare it in a package and use 'pc render' instead."


def render_cad_file(input_filename: str, input_type: str, output_filename: str, output_type: str, **options) -> None:
    """Render a CAD file to a 2D projection.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file.
        output_filename: Path to save the projection.
        output_type: The projection to write - one of PART_RENDER_FORMATS.
        options: Render parameters, e.g. 'viewport_origin' and 'viewport_up'.
    """
    reject_package_only(input_type, verb="render", advice=_ADVICE)
    write_output_file(
        input_filename,
        input_type,
        output_filename,
        output_type,
        kind="part",
        verb="Render",
        **options,
    )


def render_sketch_file(input_filename: str, input_type: str, output_filename: str, output_type: str, **options) -> None:
    """Render a sketch file to a 2D projection.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file (e.g. svg, dxf).
        output_filename: Path to save the projection.
        output_type: The projection to write - one of SKETCH_RENDER_FORMATS.
        options: Render parameters, e.g. 'viewport_origin' and 'viewport_up'.
    """
    write_output_file(
        input_filename,
        input_type,
        output_filename,
        output_type,
        kind="sketch",
        verb="Render",
        **options,
    )
