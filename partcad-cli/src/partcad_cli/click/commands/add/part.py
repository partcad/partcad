import rich_click as click  # import click
import partcad as pc
from partcad.actions.part import add_part_action
from pathlib import Path


@click.command(help="Add a part")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The part description (also used by LLMs).",
    required=False,
    show_envvar=True,
)
@click.option(
    "--ai",
    "provider",
    type=click.Choice(
        [
            "google",
            "openai",
        ]
    ),
    help="Generative AI provider.",
    required=False,
    show_envvar=True,
)
# TODO-93: @alexanderilyin: Make this optional and detect the kind from the PATH
@click.argument(
    "kind",
    type=click.Choice(
        [
            "cadquery",
            "build123d",
            "scad",
            "step",
            "brep",
            "stl",
            "3mf",
            "obj",
            "ai-cadquery",
            "ai-openscad",
        ]
    ),
    # help="Type of the part",
)
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_obj
def cli(ctx, desc, kind, provider, path):
    """
    CLI command to add a part to the project without copying.
    """
    project = ctx.get_project(pc.ROOT)
    if not project:
        raise click.UsageError("Failed to retrieve the project.")

    file_path = Path(path)
    if not file_path.exists():
        raise click.UsageError(f"ERROR: The part file '{file_path}' does not exist.")

    config = {}
    if desc:
        config["desc"] = desc
    if provider:
        config["provider"] = provider

    add_part_action(project, kind, path, config)
    click.echo(f"Part '{Path(path).stem}' added to the project.")
