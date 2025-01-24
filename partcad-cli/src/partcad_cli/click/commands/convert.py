import rich_click as click
from partcad.actions.part_actions import convert_part_action, resolve_enrich_action
from partcad.context import Context
import partcad.logging as pc_logging
import partcad.utils as pc_utils

@click.command(help="Convert parts to another format or resolve enrich parts to their original types.")
@click.argument("part_name", type=str, required=True)
@click.option(
    "-t", "--target-format",
    help="Target format for conversion.",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    required=False,
)
@click.pass_obj
def cli(ctx: Context, part_name: str, target_format: str):
    """
    CLI command to convert a part to a new format or resolve an enrich part.
    """
    project_name, object_name = pc_utils.resolve_resource_path(ctx.get_current_project_path(), part_name)
    project = ctx.get_project(project_name)

    if not project:
        raise click.UsageError(f"Failed to find project '{project_name}'.")

    part_config = project.get_part_config(object_name)
    if not part_config:
        raise click.UsageError(f"Part '{object_name}' not found in project '{project.name}'.")

    if part_config["type"] == "enrich":
        resolve_enrich_action(project, part_name)
        pc_logging.info(f"Enrich part '{object_name}' resolved.")
    elif target_format:
        convert_part_action(project, object_name, target_format)
        pc_logging.info(f"Part '{object_name}' converted to format '{target_format}'.")
    else:
        click.echo("Error: For non-enrich parts, target format must be specified.", err=True)
