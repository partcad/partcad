import rich_click as click
from pathlib import Path
from partcad.converter import convert_cad_file
import partcad.logging as logging


@click.command(help="Convert CAD files between formats")
@click.option(
    "--input", "input_type",
    type=click.Choice(["step", "brep", "stl", "3mf", "scad"]),
    help="Input file type. Inferred from filename if not provided.",
    required=False,
)
@click.option(
    "--output", "output_type",
    type=click.Choice(
      [
            "step",
            "brep",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
        ]),
    help="Output file type. Inferred from filename if not provided.",
    required=False,
)
@click.argument("input_filename", type=click.Path(exists=True))
@click.argument("output_filename", type=click.Path(), required=False)
def cli(input_type, output_type, input_filename, output_filename):
    """
    Convert CAD files from one format to another.
    """
    def infer_type_from_filename(filename):
        extension = Path(filename).suffix.lower()
        return {
        ".step": "step",
        ".stl": "stl",
        ".3mf": "3mf",
        ".scad": "scad",
        ".brep": "brep",
        ".json": "threejs",
        ".obj": "obj",
        ".gltf": "gltf",
        ".md": "markdown",
        ".txt": "txt",
        }.get(extension, None)

    # Infer types if not explicitly provided
    input_type = input_type or infer_type_from_filename(input_filename)
    if not input_type:
        logging.error("Cannot infer input type. Please specify --input explicitly.")
        raise click.Abort()

    output_type = output_type or infer_type_from_filename(output_filename)
    if not output_type:
        logging.error("Cannot infer output type. Please specify --output explicitly.")
        raise click.Abort()

    if not output_filename:
        output_filename = Path(input_filename).stem + f".{output_type}"

    # Perform conversion
    try:
        logging.info(f"Converting {input_filename} ({input_type}) to {output_filename} ({output_type})...")
        convert_cad_file(input_filename, input_type, output_filename, output_type)
        logging.info(f"Conversion complete: {output_filename}")
    except Exception as e:
        logging.error(f"Error during conversion: {e}")
        raise click.Abort()
