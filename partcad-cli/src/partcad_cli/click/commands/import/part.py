#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.actions.part import import_part_action
from ...commands.convert import SUPPORTED_CONVERT_FORMATS
from ...cli_context import CliContext

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
def cli(cli_ctx: CliContext, package: str, existing_part: str, target_format: str, desc: str):
    """
    CLI command to import a part by copying and adding it to the project, with optional format conversion.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

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

        # Get the target package
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name

        pc.logging.info(f"Importing part: {existing_part} ({part_type})")
        name = file_path.stem
        config = {"desc": desc} if desc else {}
        try:
            # pc.logging.Process() is done inside import_part_action()
            import_part_action(package_obj, part_type, name, existing_part, config, target_format)
            pc.logging.info(f"Successfully imported part: {name}")
            click.echo(f"Part '{name}' imported successfully.")
        except Exception as e:
            pc.logging.exception(f"Error importing part '{name}' ({part_type})")
            raise click.ClickException(f"Error importing part '{name}' ({part_type}): {e}") from e


def __detect_script_type(file_path: Path, lines_check_range: int = 50) -> str | None:
    """
    Detect if a Python script is a CadQuery or Build123d model based on its imports.

    Args:
        file_path (Path): Path to the Python script.

    Returns:
        str: "cadquery", "build123d" or None if not detected.
    """

    try:
        with file_path.open("r", encoding="utf-8") as f:
            for _ in range(lines_check_range):
                line = f.readline()

                if "import cadquery" in line or "from cadquery" in line:
                    return "cadquery"
                if "import build123d" in line or "from build123d" in line:
                    return "build123d"

    except Exception as e:
        pc.logging.warning(f"Could not read script file {file_path}: {e}")

    return None
