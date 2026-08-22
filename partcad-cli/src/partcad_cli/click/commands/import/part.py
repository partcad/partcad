#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import partcad_utils.logging as pc_logging
import rich_click as click

from ...commands.convert.part import SUPPORTED_CONVERT_FORMATS
from ...service import run

# part_type: [file_extensions]
SUPPORTED_IMPORT_FORMATS_WITH_EXT = {
    "step": ["step", "stp"],
    "brep": ["brep"],
    "stl": ["stl"],
    "3mf": ["3mf"],
    "threejs": ["json"],
    "obj": ["obj"],
    "gltf": ["gltf", "glb"],
    "scad": ["scad"],
    "cadquery": ["py"],
    "build123d": ["py"],
    "sdf": ["py"],
    "chili3d": ["chili"],
}


@click.command(help="Import an existing part and optionally convert its format.")
@click.argument("existing_part", type=str, required=True)
@click.option(
    "-t",
    "--target-format",
    type=click.Choice(SUPPORTED_CONVERT_FORMATS),
    help="Convert the imported part to the specified format.",
)
@click.option(
    "--desc",
    type=str,
    help="Optional description for the imported part.",
)
@click.option(
    "-P",
    "--package",
    help="Package to import the object to",
    type=str,
    default=".",
)
@click.pass_obj
def cli(cli_ctx, package: str, existing_part: str, target_format: str, desc: str):
    """
    CLI command to import a part by copying and adding it to the project, with optional format conversion.

    Served by the daemon: `--target-format` converts through sandboxed wrappers,
    whose Python runtimes belong to the daemon's environment.
    """
    file_path = Path(existing_part)
    if not file_path.exists():
        raise click.UsageError(f"File '{existing_part}' not found.")

    # Auto-detect the part type based on the file extension and content
    detected_ext = file_path.suffix.lstrip(".").lower()
    part_type = None
    for supported_type in SUPPORTED_IMPORT_FORMATS_WITH_EXT.keys():
        if detected_ext in SUPPORTED_IMPORT_FORMATS_WITH_EXT[supported_type]:
            part_type = supported_type if detected_ext != "py" else __detect_script_type(file_path)

    if not part_type:
        raise click.ClickException(
            f"Cannot determine file type for '{existing_part}'. "
            f"Supported part types: {', '.join(set(SUPPORTED_IMPORT_FORMATS_WITH_EXT.keys()))}. "
        )

    params = {
        "obj_kind": "part",
        # Absolute: the daemon does not share the client's working directory.
        "source": os.path.abspath(existing_part),
        "part_type": part_type,
        "package": package,
    }
    if target_format:
        params["target_format"] = target_format
    if desc:
        params["desc"] = desc

    result = run(cli_ctx, "import.object", params, span_name="import part", needs_context=True)
    click.echo(f"Part '{(result or {}).get('name', file_path.stem)}' imported successfully.")


def __detect_script_type(file_path: Path, lines_check_range: int = 50) -> str | None:
    """
    Detect if a Python script is a CadQuery, Build123d or SDF model based on its imports.

    Args:
        file_path (Path): Path to the Python script.

    Returns:
        str: "cadquery", "build123d", "sdf" or None if not detected.
    """

    try:
        with file_path.open("r", encoding="utf-8") as f:
            for _ in range(lines_check_range):
                line = f.readline()

                if "import cadquery" in line or "from cadquery" in line:
                    return "cadquery"
                if "import build123d" in line or "from build123d" in line:
                    return "build123d"
                if "import sdf" in line or "from sdf" in line:
                    return "sdf"

    except Exception as e:
        pc_logging.warning(f"Could not read script file {file_path}: {e}")

    return None
