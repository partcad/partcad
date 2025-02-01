import rich_click as click
import partcad as pc
from partcad.actions.part_actions import convert_part_action
import partcad.logging as logging

@click.command(help="Convert parts, assemblies, or scenes to another format and update their type.")
@click.argument("object_name", type=str, required=True)
@click.option("-t", "--target-format", help="Target conversion format.",
              type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]), required=True)
@click.option("-O", "--output-dir", help="Output directory for converted files.",
              type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-i", "--in-place", help="Update object's type in place.", is_flag=True, default=False)
@click.option("--dry-run", help="Simulate conversion without making any changes.", is_flag=True)
@click.pass_obj
def cli(ctx, object_name, target_format, output_dir, in_place, dry_run):
    """
    CLI command to convert an object (part, assembly, or scene) to a new format.
    """
    logging.info(f"Starting conversion for '{object_name}' to '{target_format}', in_place={in_place}, dry_run={dry_run}")

    project = ctx.get_project(pc.ROOT)
    convert_part_action(project, object_name, target_format, output_dir, in_place, dry_run)

    click.echo(f"Conversion of '{object_name}' to format '{target_format}' completed.")
