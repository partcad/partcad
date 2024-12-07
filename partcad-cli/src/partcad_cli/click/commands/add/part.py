import rich_click as click  # import click
import partcad as pc
from pathlib import Path


@click.command(help="Add a part")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The part description (also used by LLMs).",
    required=False,
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
)
# TODO: @alexanderilyin: Make this optional and detect the kind from the PATH
@click.argument(
    "kind",
    type=click.Choice(
        [
            "cadquery",
            "build123d",
            "scad",
            "step",
            "stl",
            "3mf",
            "ai-cadquery",
            "ai-openscad",
        ]
    ),
    # help="Type of the part",
)
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_obj
def cli(ctx, desc, kind, provider, path):
    with pc.logging.Process("AddPart", "this"):
        prj = ctx.get_project(pc.ROOT)
        config = {}
        if desc:
            config["desc"] = desc
        if provider:
            config["provider"] = provider
        if prj.add_part(kind, path, config):
            Path(path).touch()
