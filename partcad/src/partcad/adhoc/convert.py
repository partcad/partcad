#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from pathlib import Path
import shutil
import tempfile

from .. import logging as pc_logging
from ..context import Context


def convert_cad_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """
    Convert a CAD file from one format to another.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file.
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file.
    """
    input_path = Path(input_filename).resolve()  # Use absolute path of the input file

    # Generate a temporary configuration file for PartCAD
    temp_dir = Path(tempfile.mkdtemp())  # Create a temporary directory for PartCAD config
    try:
        generate_partcad_config(temp_dir, input_type, input_path)

        # Initialize PartCAD context and load the project
        ctx = Context(root_path=temp_dir, search_root=False)
        with pc_logging.Process("Convert", "adhoc"):
            project = ctx.get_project("/")
            part = project.get_part("input_part")
            if not part:
                raise RuntimeError("Failed to load the input part: no part returned")

            shape = asyncio.run(part.get_wrapped(ctx))
            if not shape:
                raise RuntimeError("Failed to load the input part: no shape returned")
            pc_logging.info(f"Loaded input part: {input_path}")
            pc_logging.info(f"Shape: {type(shape)}")

            if part.errors:
                raise RuntimeError(f"Failed to load the input part: {part.errors}")

            # Render the part to the desired output format
            part.render(ctx=ctx, format_name=output_type, project=project, filepath=output_filename)

    except Exception as e:
        raise RuntimeError(f"Failed to convert: {e.with_traceback(None)}")
    finally:
        shutil.rmtree(temp_dir)  # Cleanup temporary files


def generate_partcad_config(temp_dir: Path, input_type: str, temp_input_path: Path) -> None:
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        input_type (str): Input file format type.
        temp_input_path (Path): Path to the copied input file.
    """
    config_path = temp_dir / "partcad.yaml"
    config_content = f"""
parts:
  input_part:
    type: {input_type}
    path: '{temp_input_path}'
    """
    with open(config_path, "w", encoding="utf-8") as config_file:
        config_file.write(config_content)
