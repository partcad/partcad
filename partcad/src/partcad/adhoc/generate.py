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


def generate_partcad_config(temp_dir: Path, part_type: str, description: str, provider: str) -> None:
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        part_type (str): Type of the part.
        description (str): Description of the CAD file being generated.
        provider (str): Generative AI provider.
    """
    section = "parts"
    name = "gen_part"

    config = f"""
{section}:
  {name}:
    type: {part_type}
    provider: '{provider}'
    desc: '{description}'
    """
    config_path = temp_dir / "partcad.yaml"
    config_path.write_text(config.strip() + "\n", encoding="utf-8")


def generate_cad_file(provider: str, kind: str, description: str, path: str = None) -> None:
    """
    Generate a CAD file using specified provider and type.

    Args:
        provider (str): Generative AI provider.
        kind (str): Type of the part.
        description (str): Description of the CAD file being generated.
    """
    temp_dir = Path(tempfile.mkdtemp())

    try:
        generate_partcad_config(temp_dir, kind, description, provider)

        ctx = Context(root_path=temp_dir, search_root=False)
        with pc_logging.Process("Generate", "adhoc"):
            project = ctx.get_project("//")
            part = project.get_part("gen_part")

            if not part:
                raise RuntimeError("Failed to load the input part: no part returned")

            if not path:
                current_dir = Path.cwd()
                target_path = current_dir / Path(part.path).name
                part.path = str(target_path)

            asyncio.run(get_shape_async(part, ctx))

            if part.errors:
                raise RuntimeError(f"Failed to load the part: {part.errors}")

    except Exception as e:
        raise RuntimeError(f"Failed to generate: {e}")
    finally:
        shutil.rmtree(temp_dir)


async def get_shape_async(part, ctx):
    """
    Run the get_shape method of a part asynchronously.

    Args:
        part: The part object to process.
    """
    try:
        await part.get_shape(ctx)
    except Exception as e:
        pc_logging.error(f"Error in get_shape: {e}")
