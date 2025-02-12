import rich_click as click
from partcad.actions.part_actions import convert_part_action
from partcad.context import Context
import partcad.logging as pc_logging

@click.command(help="Convert parts, assemblies, or scenes to another format and update their type.")
@click.argument("object_name", type=str, required=True)
@click.option(
    "-t", "--target-format",
    help="Target conversion format.",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    required=True
)
@click.option(
    "-O", "--output-dir",
    help="Output directory for converted files.",
    type=click.Path(exists=True, file_okay=False, dir_okay=True)
)
@click.option("--dry-run", help="Simulate conversion without making any changes.", is_flag=True)
@click.pass_obj
def cli(ctx: Context, object_name: str, target_format: str, output_dir: str, dry_run: bool):
    """
    CLI command to convert an object (part, assembly, or scene) to a new format.

    :param ctx: PartCAD context
    :param object_name: Name of the object to convert
    :param target_format: Desired target format
    :param output_dir: (Optional) Output directory for the converted file
    :param dry_run: If True, simulates conversion without actual changes
    """
    pc_logging.info(f"Starting conversion: '{object_name}' → '{target_format}', dry_run={dry_run}")

    project = ctx.get_project("")
    if not project:
        pc_logging.error("Project retrieval failed. Ensure you are inside a valid PartCAD project.")
        raise click.UsageError("Failed to retrieve the project.")

    convert_part_action(project, object_name, target_format, output_dir=output_dir, dry_run=dry_run)

    msg = f"Conversion of '{object_name}' to '{target_format}' completed."
    pc_logging.info(msg)
    click.echo(msg)
