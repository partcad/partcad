import rich_click as click
import partcad as pc
from partcad.actions.part_actions import convert_part_action

@click.command(help="Convert parts to another format and update their type.")
@click.argument("part_name", type=str, required=True)
@click.option("-t", "--target-format", help="Target format for conversion.", type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]), required=True)
@click.pass_obj
def cli(ctx, part_name, target_format):
    """
    CLI command to convert a part to a new format.
    """
    project = ctx.get_project(pc.ROOT)
    convert_part_action(project, part_name, target_format)
    click.echo(f"Part '{part_name}' converted to format '{target_format}'.")
