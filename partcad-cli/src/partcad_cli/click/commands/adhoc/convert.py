import rich_click as click
from pathlib import Path
from partcad.adhoc.convert import convert_cad_file
import partcad.logging as logging
from partcad.part_types import PartTypes


INPUT_EXT_MAP = PartTypes.convert_input.as_dict()
CONVERT_EXT_MAP = PartTypes.convert_output.as_dict()


@click.command(help="Convert CAD files between formats.")
@click.option(
    "--input",
    "input_type",
    type=click.Choice(PartTypes.convert_input.types()),
    help="Input file type. Inferred from filename if not provided.",
)
@click.option(
    "--output",
    "output_type",
    type=click.Choice(PartTypes.convert_output.types()),
    help="Output file type. Inferred from output filename if not provided.",
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
def cli(input_type, output_type, input_filename: str, output_filename):
    """
    Convert CAD files from one format to another.
    """
    input_path = Path(input_filename)
    input_ext = input_path.suffix.lstrip(".")

    # Infer input type
    if not input_type:
        candidates = [key for key, value in INPUT_EXT_MAP.items() if input_ext == value]

        if not candidates:
            logging.error(f"Unknown input extension '{input_ext}'. Please specify --input.")
            raise click.Abort()
        if len(candidates) > 1:
            names = [f for f in candidates]
            logging.error(f"Ambiguous input extension '{input_ext}'. Use --input to specify one of {names}.")
            raise click.Abort()
        input_type = candidates[0]

    # Infer output filename from input + output type
    if not output_filename and output_type:
        output = PartTypes.convert_output.get_format(output_type)
        output_filename = str(input_path.with_suffix(f".{output.ext}"))

    # Infer output type from output filename
    if output_filename:
        output_ext = Path(output_filename).suffix.lstrip(".")
        candidates = [key for key, value in CONVERT_EXT_MAP.items() if output_ext == value]
        if not output_type:
            if not candidates:
                logging.error(f"Unknown output extension '{output_ext}'. Please specify --output.")
                raise click.Abort()
            if len(candidates) > 1:
                names = [f for f in candidates]
                logging.error(f"Ambiguous output extension '{output_ext}'. Use --output to specify one of {names}.")
                raise click.Abort()
            output_type = candidates[0]

    if not output_type:
        logging.error(
            "Cannot determine output format. Use --output or provide output filename with recognizable extension."
        )
        raise click.Abort()

    try:
        convert_cad_file(str(input_path), input_type, str(output_filename), output_type)
    except Exception as e:
        logging.error(f"Error during conversion: {e}")
        raise click.Abort()
