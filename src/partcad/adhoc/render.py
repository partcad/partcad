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

The mechanism is the same throwaway package (`adhoc.py`), which is why
`pc adhoc render` takes what `pc render` takes even though there is no
`partcad.yaml` to configure it in: the viewport and `reproducible` arrive as
export parameters, on top of what the implementation would otherwise default to;
the input's parameter values are declared on it in the throwaway package; and a
package to read the file type from is imported into it.
"""

from .adhoc import reject_package_only, write_output_file

# The 2D projections '//builtin/render' implements, which an ad-hoc render can
# always write. A file type a package implements itself is written by naming
# that package as 'options_package', which the throwaway package then imports.
PART_RENDER_FORMATS = ["svg", "png", "jpeg", "dxf"]

# The same, for a sketch. A sketch is already flat, so all four mean something
# for one too - and 'dxf' more than for a part, since a drawing is what a sketch
# is for.
SKETCH_RENDER_FORMATS = ["svg", "png", "jpeg", "dxf"]

_ADVICE = "Declare it in a package and use 'pc render' instead."


def render_cad_file(input_filename: str, input_type: str, output_filename: str, output_type: str, **options) -> str:
    """Render a CAD file to a 2D projection, and return the path written.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file.
        output_filename: Path to save the projection, or None to name it after
            the input in 'output_dir' (see 'adhoc.write_output_file').
        output_type: The projection to write - one of PART_RENDER_FORMATS, or a
            file type the 'options_package' declares.
        options: 'parameters', 'options_package' and 'output_dir' (see
            'adhoc.write_output_file'), and render parameters, e.g.
            'viewport_origin', 'viewport_up' and 'reproducible'.
    """
    reject_package_only(input_type, verb="render", advice=_ADVICE)
    return write_output_file(
        input_filename,
        input_type,
        output_filename,
        output_type,
        kind="part",
        verb="Render",
        **options,
    )


def render_sketch_file(input_filename: str, input_type: str, output_filename: str, output_type: str, **options) -> str:
    """Render a sketch file to a 2D projection, and return the path written.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file (e.g. svg, dxf).
        output_filename: Path to save the projection, or None (see
            'render_cad_file').
        output_type: The projection to write - one of SKETCH_RENDER_FORMATS, or
            a file type the 'options_package' declares.
        options: As for 'render_cad_file'.
    """
    return write_output_file(
        input_filename,
        input_type,
        output_filename,
        output_type,
        kind="sketch",
        verb="Render",
        **options,
    )
