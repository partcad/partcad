#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.shape import SKETCH_EXTENSION_MAPPING
from partcad.adhoc.convert import convert_sketch_file
from ....cli_context import CliContext


@click.command(help="Convert sketch files between formats (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(list(SKETCH_EXTENSION_MAPPING.keys())),
    help="Input sketch type. Inferred from filename if not provided.",
)
@click.option(
    "--output",
    "output_type",
    type=click.Choice(list(SKETCH_EXTENSION_MAPPING.keys())),
    help="Output sketch type. Inferred from filename if not provided.",
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(cli_ctx: CliContext, input_type, output_type, input_filename, output_filename):
    """
    Convert sketch files from one format to another without modifying project configuration.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        input_path = Path(input_filename).resolve()
        output_path = Path(output_filename).resolve() if output_filename else None

        # Reverse map: .ext -> sketch type
        EXT_TO_SKETCH_TYPE = {f".{v}": k for k, v in SKETCH_EXTENSION_MAPPING.items()}

        input_type = input_type or EXT_TO_SKETCH_TYPE.get(input_path.suffix.lower())
        output_type = output_type or (EXT_TO_SKETCH_TYPE.get(output_path.suffix.lower()) if output_path else None)

        if not input_type:
            click.echo("Error: Cannot infer input sketch type. Please specify --input explicitly.", err=True)
            raise click.Abort()
        if not output_type:
            click.echo("Error: Cannot infer output sketch type. Please specify --output explicitly.", err=True)
            raise click.Abort()


        if output_path is None:
            output_path = input_path.with_suffix(f".{SKETCH_EXTENSION_MAPPING[output_type]}")

        try:
            pc.logging.info(f"Converting {input_path} ({input_type}) to {output_path} ({output_type})...")
            convert_sketch_file(str(input_path), input_type, str(output_path), output_type)
            pc.logging.info(f"Conversion complete: {output_path}")
        except Exception as e:
            pc.logging.error("Failed to convert: %s", e)
            raise click.Abort()
