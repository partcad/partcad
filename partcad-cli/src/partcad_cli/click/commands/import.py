import shutil
import rich_click as click
from pathlib import Path
import partcad as pc
from partcad.actions.part_actions import import_part_action

@click.command(help="Import an existing part from another project and optionally convert its format.")
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
    "target_format",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    required=False,
    help="Convert the imported part to the specified format.",
)
@click.option(
    "--desc",
    "desc",
    type=str,
    help="Optional description for the imported part.",
    required=False,
)
@click.pass_obj
def cli(ctx, kind, source_path, desc):
    """
    CLI command to import a part by copying and adding to the project.
    """
    project = ctx.get_project(pc.ROOT)
    if not project:
        raise click.UsageError("Failed to retrieve the project.")

    name = Path(source_path).stem
    config = {}
    if desc:
        config["desc"] = desc

    import_part_action(project, kind, name, source_path, config)
    click.echo(f"Part '{name}' imported into the project.")
