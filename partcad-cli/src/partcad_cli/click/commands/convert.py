import rich_click as click
from partcad.actions.part_actions import convert_part_action, resolve_enrich_action
from partcad.context import Context
import partcad.logging as pc_logging

@click.command(help="Convert parts to another format or resolve enrich parts.")
@click.argument("object_name", type=str, required=True)
@click.option(
    "-t", "--target-format",
    help="Target conversion format.",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
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
    CLI command to convert an object (part, assembly, or scene) to a new format or resolve an enrich part.

    :param ctx: PartCAD context
    :param object_name: Name of the object to convert or resolve
    :param target_format: Desired target format (if applicable)
    :param output_dir: (Optional) Output directory for the converted file
    :param dry_run: If True, simulates conversion without actual changes
    """
    pc_logging.info(f"Starting conversion: '{object_name}' -> '{target_format}', dry_run={dry_run}")

    project = ctx.get_project("")
    if not project:
        pc_logging.error("Project retrieval failed. Ensure you are inside a valid PartCAD project.")
        raise click.UsageError("Failed to retrieve the project.")

    part = ctx.get_part(object_name)
    if not part:
        raise click.UsageError(f"Object '{object_name}' not found in project.")

    try:
        part_type = part.config.get("type", "unknown")
        pc_logging.info(f"Identified '{object_name}' as type '{part_type}'.")

        if part_type == "enrich":
            resolve_enrich_action(project, object_name, dry_run=dry_run)
            pc_logging.info(f"Resolved enrich part '{object_name}'.")

            if not target_format:
                click.echo(f"Resolved enrich part '{object_name}'.")
                return

            # Refresh context after resolving enrich
            ctx = Context(project.ctx.root_path)
            project = ctx.get_project("")

        if not target_format:
            raise click.UsageError("Error: Target format must be specified for non-enrich parts.")

        convert_part_action(project, object_name, target_format, output_dir=output_dir, dry_run=dry_run)
    except Exception as e:
        raise click.UsageError(str(e)) from e
    pc_logging.info(f"Conversion of '{object_name}' to '{target_format}' completed.")
    click.echo(f"Converted '{object_name}' to '{target_format}'.")
