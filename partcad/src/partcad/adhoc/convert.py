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


def generate_partcad_config(temp_dir: Path, input_type: str, temp_input_path: Path, kind: str = "part") -> None:
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        input_type (str): Input file format type.
        temp_input_path (Path): Path to the copied input file.
        kind (str): Either "part" or "sketch" (default is "part")
    """
    section = "parts" if kind == "part" else "sketches"
    name = "input_part" if kind == "part" else "input_sketch"

    config = f"""
{section}:
  {name}:
    type: {input_type}
    path: '{temp_input_path}'
    """
    config_path = temp_dir / "partcad.yaml"
    config_path.write_text(config.strip() + "\n", encoding="utf-8")


def convert_cad_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """
    Convert a CAD file from one format to another.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file.
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file.
    """
    input_path = Path(input_filename).resolve()
    temp_dir = Path(tempfile.mkdtemp())

    try:
        generate_partcad_config(temp_dir, input_type, input_path, kind="part")

        ctx = Context(root_path=temp_dir, search_root=False)
        with pc_logging.Process("Convert", "adhoc"):
            project = ctx.get_project("//")
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

            part.render(ctx=ctx, format_name=output_type, project=project, filepath=output_filename)

    except Exception as e:
        raise RuntimeError(f"Failed to convert: {e}")
    finally:
        shutil.rmtree(temp_dir)


def convert_sketch_file(input_filename: str, input_type: str, output_filename: str, output_type: str) -> None:
    """
    Convert a sketch file from one format to another using an adhoc PartCAD context.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file (e.g., svg, dxf).
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file (e.g., svg, dxf).
    """
    input_path = Path(input_filename).resolve()
    temp_dir = Path(tempfile.mkdtemp())

    try:
        generate_partcad_config(temp_dir, input_type, input_path, kind="sketch")

        ctx = Context(root_path=temp_dir, search_root=False)
        with pc_logging.Process("Convert", "adhoc-sketch"):
            project = ctx.get_project("/")
            sketch = project.get_sketch("input_sketch")
            if not sketch:
                raise RuntimeError("Failed to load the input sketch: no sketch returned")

            shape = asyncio.run(sketch.get_wrapped(ctx))
            if not shape:
                raise RuntimeError("Failed to load the input sketch: no shape returned")

            pc_logging.debug(f"Loaded input sketch: {input_path}")

            if sketch.errors:
                raise RuntimeError(f"Failed to load the input sketch: {sketch.errors}")

            sketch.render(ctx=ctx, format_name=output_type, project=project, filepath=output_filename)

    except Exception as e:
        raise RuntimeError("Failed to convert sketch") from e
    finally:
        shutil.rmtree(temp_dir)
