import shutil
import rich_click as click
from pathlib import Path
import partcad as pc
from partcad.actions.part_actions import import_part_action

@click.command(help="Import an existing part and optionally convert its format.")
@click.argument(
    "part_type",
    type=click.Choice(["stl", "step", "brep", "3mf", "obj", "gltf", "threejs"]),
    required=True
)
@click.argument(
    "existing_part",
    type=str,
    required=True
)
@click.option(
    "-t",
    "--target-format",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    required=False,
    help="Convert the imported part to the specified format.",
)
@click.option(
    "--desc",
    type=str,
    help="Optional description for the imported part.",
    required=False,
)
@click.pass_obj
def cli(ctx, part_type, existing_part, target_format, desc):
    """
    CLI command to import a part by copying and adding to the project, with optional format conversion.
    """
    project = ctx.get_project(pc.ROOT)
    if not project:
        raise click.UsageError("Failed to retrieve the project.")

    name = Path(existing_part).stem
    config = {"desc": desc} if desc else {}

    import_part_action(project, part_type, name, existing_part, config, target_format)
    click.echo(f"Part '{name}' imported into the project.")
