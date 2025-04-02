#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.shape import PART_EXTENSION_MAPPING
from partcad.adhoc.convert import convert_cad_file
from ....cli_context import CliContext


@click.command(help="Convert CAD files between formats (ad-hoc mode).")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(list(PART_EXTENSION_MAPPING.keys())),
    help="Input file type. Inferred from filename if not provided.",
)
@click.option(
    "--output",
    "output_type",
    type=click.Choice(list(PART_EXTENSION_MAPPING.keys())),
    help="Output file type. Inferred from filename if not provided.",
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_obj
def cli(cli_ctx: CliContext, input_type, output_type, input_filename, output_filename):
    """
    Convert CAD files from one format to another without modifying project configuration.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        input_path = Path(input_filename).resolve()
        output_path = Path(output_filename).resolve() if output_filename else None

        # Reverse map from extension to part type
        EXT_TO_PART_TYPE = {f".{v}": k for k, v in PART_EXTENSION_MAPPING.items()}

        # Infer types if needed
        input_type = input_type or EXT_TO_PART_TYPE.get(input_path.suffix.lower())
        output_type = output_type or (EXT_TO_PART_TYPE.get(output_path.suffix.lower()) if output_path else None)

        if not input_type:
            pc.logging.error("Cannot infer input type. Please specify --input explicitly.")
            raise click.Abort()
        if not output_type:
            pc.logging.error("Cannot infer output type. Please specify --output explicitly.")
            raise click.Abort()

        if output_path is None:
            output_path = input_path.with_suffix(f".{PART_EXTENSION_MAPPING[output_type]}")

        try:
            pc.logging.info(f"Converting {input_path} ({input_type}) to {output_path} ({output_type})...")
            convert_cad_file(str(input_path), input_type, str(output_path), output_type)
            pc.logging.info(f"Conversion complete: {output_path}")
        except Exception as e:
            pc.logging.error(f"Error during conversion: {e}")
            raise click.Abort()
