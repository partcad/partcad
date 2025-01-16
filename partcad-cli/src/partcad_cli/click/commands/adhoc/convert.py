import rich_click as click
from pathlib import Path
import partcad.logging as logging
from partcad.converters.cad_converter import CADConverter


@click.command(help="Convert CAD files from one format to another")
@click.option(
    "--create-dirs",
    "-p",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
)
@click.option(
    "--output-dir",
    "-O",
    help="Output directory for the converted file",
    type=click.Path(file_okay=False, dir_okay=True),
)
@click.option(
    "--input",
    "-I",
    help="Input file type (e.g., stl, step)",
    type=click.Choice(
        [
            "step",
            "brep",
            "stl",
            "3mf",
            "obj",
        ],
        case_sensitive=False,
    ),
)
@click.option(
    "--output",
    "-t",
    help="Output file type (e.g., stl, step, brep)",
    type=click.Choice(
        [
            "step",
            "brep",
            "stl",
            "3mf",
            "obj",
        ],
        case_sensitive=False,
    ),
)
@click.argument("input_filename", type=click.Path())
@click.argument("output_filename", type=click.Path(), required=False)
@click.pass_context
def cli(ctx, create_dirs, output_dir, input, output, input_filename, output_filename):
    input_file = Path(input_filename)

    with logging.Process("Convert CAD File", "convert"):
        # Append the extension if missing and --input is provided
        if input and not input_file.suffix:
            input_file = input_file.with_suffix(f".{input}")

        # Validate input file existence
        if not input_file.exists():
            raise click.UsageError(f"Input file '{input_file}' does not exist.")

        # Determine output type and filename
        if output_filename:
            output_file = Path(output_filename)
            output_type = output or output_file.suffix.lstrip(".").lower()

            # Validate file extension and output type match
            expected_extension = f".{output}"
            if output and not str(output_file).endswith(expected_extension):
                raise click.UsageError(
                    f"Conflict: The specified output type '{output}' does not match the file extension '{output_file.suffix}' "
                    f"in the output filename '{output_file.name}'."
                )
        elif output:
            # Generate output filename based on input filename and output type
            output_dir_path = Path(output_dir or ".")
            output_file = output_dir_path / f"{input_file.stem}.{output}"
            output_type = output
        else:
            raise click.UsageError("You must specify either --output or <output_filename>.")

        # Ensure the output directory exists if --create-dirs is enabled
        if create_dirs:
            output_file.parent.mkdir(parents=True, exist_ok=True)
        elif not output_file.parent.exists():
            raise click.UsageError(
                f"Output directory '{output_file.parent}' does not exist. Use --create-dirs to create it."
            )

        # Validate input and output formats
        input_type = input or input_file.suffix.lstrip(".").lower()
        if not CADConverter.is_supported_format(input_type) or not CADConverter.is_supported_format(output_type):
            raise click.UsageError(
                f"Conversion from {input_type} to {output_type} is not supported."
            )

        # Perform the conversion
        try:
            CADConverter.convert(str(input_file), str(output_file), input_type, output_type)
            logging.info(f"Successfully converted {input_file} to {output_file}.")
        except Exception as e:
            logging.error(f"Conversion failed: {e}")
            raise click.ClickException(str(e))
          
