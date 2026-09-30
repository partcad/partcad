#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ....service import run
from ....viewport import viewport_options, viewport_params

# PartCAD sketch types (partcad.shape.SKETCH_EXTENSION_MAPPING keys), inlined so
# the thin CLI does not import the heavy partcad package.
SKETCH_TYPES = ["svg", "dxf", "cadquery", "build123d"]

# The projections that can be written of one. 'svg' and 'dxf' appear on both
# sides and mean different things there: as an input they are the sketch itself,
# as an output a drawing of it - which is why 'pc adhoc render sketch a.svg b.svg'
# is a projection and not a copy.
RENDER_TYPES = ["svg", "png", "jpeg", "dxf"]


@click.command(help="Render a sketch file to a 2D image (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(SKETCH_TYPES),
    help="Input sketch type. Inferred from filename if not provided.",
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
    """Render a sketch file to a 2D image without modifying project configuration."""
    run(
        cli_ctx,
        "adhoc.render",
        {
            "kind": "sketch",
            "input_type": input_type,
            "output_type": output_type,
            # Absolute so the daemon reads/writes in the user's cwd.
            "input_filename": os.path.abspath(input_filename),
            "output_filename": os.path.abspath(output_filename) if output_filename else None,
            **viewport_params(view, viewport_origin, viewport_up),
        },
        needs_context=False,
    )
