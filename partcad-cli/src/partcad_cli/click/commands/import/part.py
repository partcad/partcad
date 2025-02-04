import rich_click as click
from pathlib import Path
import partcad.logging as pc_logging
from partcad.actions.part_actions import import_part_action
from partcad.context import Context

@click.command(help="Import an existing part and optionally convert its format.")
@click.argument(
    "part_type",
    type=click.Choice(["stl", "step", "brep", "3mf", "obj", "gltf", "threejs"]),
    required=True
)
@click.argument("existing_part", type=str, required=True)
@click.option(
    "-t", "--target-format",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    help="Convert the imported part to the specified format."
)
@click.option(
    "--desc",
    type=str,
    help="Optional description for the imported part."
)
@click.pass_obj
def cli(ctx: Context, part_type: str, existing_part: str, target_format: str, desc: str):
    """
    CLI command to import a part by copying and adding it to the project, with optional format conversion.
    """
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
