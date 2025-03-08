import rich_click as click
from pathlib import Path
import partcad.logging as pc_logging
from partcad.actions.part import import_part_action
from partcad.context import Context
from partcad_cli.click.commands.convert import SUPPORTED_CONVERT_FORMATS

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
    "-t", "--target-format",
    type=click.Choice(SUPPORTED_CONVERT_FORMATS),
    help="Convert the imported part to the specified format."
)
@click.option(
    "--desc",
    type=str,
    help="Optional description for the imported part."
)
@click.pass_obj
def cli(ctx: Context, existing_part: str, target_format: str, desc: str):
    """
    CLI command to import a part by copying and adding it to the project, with optional format conversion.
    """
    file_path = Path(existing_part)

    if not file_path.exists():
        raise click.UsageError(f"File '{existing_part}' not found.")

    detected_ext = file_path.suffix.lstrip(".").lower()
    for supported_type in SUPPORTED_IMPORT_FORMATS_WITH_EXT.keys():
        if detected_ext in SUPPORTED_IMPORT_FORMATS_WITH_EXT[supported_type]:
            part_type = supported_type if detected_ext != "py" else __detect_script_type(file_path)
        else:
            raise click.ClickException(
                f"Cannot determine file type for '{existing_part}'. "
                f"Supported part types: {', '.join(set(SUPPORTED_IMPORT_FORMATS_WITH_EXT.keys()))}. "
            )

    pc_logging.info(f"Importing part: {existing_part} ({part_type})")

    project = ctx.get_project("")
    if not project:
        pc_logging.error("Project retrieval failed.")
        raise click.ClickException("Failed to retrieve the project.")

    name = Path(existing_part).stem

    config = {"desc": desc} if desc else {}

    try:
        import_part_action(project, part_type, name, existing_part, config, target_format)
        pc_logging.info(f"Successfully imported part: {name}")
        click.echo(f"Part '{name}' imported successfully.")
    except Exception as e:
        pc_logging.exception(f"Error importing part '{name}' ({part_type})")
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
        pc_logging.warning(f"Could not read script file {file_path}: {e}")

    return None
