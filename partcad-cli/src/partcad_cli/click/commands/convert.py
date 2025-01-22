import rich_click as click
import partcad as pc
from partcad.actions.part_actions import convert_part_action, resolve_enrich_action
from partcad.context import Context
from partcad.part import Part
import partcad.logging as pc_logging
import partcad.utils as pc_utils
import os

@click.command(help="Convert parts to another format or resolve enrich parts to their original types.")
@click.argument("part_name", type=str, required=True)
@click.option("-t", "--target-format", help="Target format for conversion.", type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]), required=False)
@click.pass_obj
def cli(ctx: Context, part_name, target_format):
    """
    CLI command to convert a part to a new format or resolve an enrich part.
    """
    pc_logging.info(f"Starting conversion for part: {part_name}")

    # Resolve the resource path to determine project and object name
    project_name, object_name = pc_utils.resolve_resource_path(ctx.get_current_project_path(), part_name)

    # Fetch the project
    project = ctx.get_project(project_name)
    if not project:
        raise click.UsageError(f"Failed to find a project in '{project_name}'.")

    pc_logging.info(f"Loaded project: {project.name} at {project.path}")

    # Get the part configuration
    part_config = project.get_part_config(object_name)
    if not part_config:
        raise click.UsageError(f"Part '{object_name}' not found in project '{project.name}'.")

    pc_logging.info(f"Part configuration for '{object_name}': {part_config}")

    # Check if the part is of type 'enrich'
    if part_config["type"] == "enrich":
        pc_logging.info(f"Resolving enrich part: {object_name}")
        resolve_enrich_action(ctx, part_name)
        pc_logging.info(f"Enrich part '{object_name}' resolved to its original type.")
    elif target_format:
        pc_logging.info(f"Converting part '{object_name}' to format '{target_format}'")
        convert_part_action(project, object_name, target_format)
        pc_logging.info(f"Part '{object_name}' converted to format '{target_format}'.")
    else:
        pc_logging.error("Error: For non-enrich parts, target format must be specified.")
        click.echo("Error: For non-enrich parts, target format must be specified.", err=True)
