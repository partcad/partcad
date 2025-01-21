import rich_click as click  # import click
import partcad as pc
from pathlib import Path
from partcad.sentry import tracer as pc_tracer


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
            "ai-cadquery",
            "ai-openscad",
        ]
    ),
    # help="Type of the part",
)
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_obj
@pc_tracer.start_as_current_span("Command [pc add part]")
def cli(ctx, desc, kind, provider, path):
    prj = ctx.get_project(pc.ROOT)
    with pc.logging.Process("AddPart", prj.name):
        config = {}
        if desc:
            config["desc"] = desc
        if provider:
            config["provider"] = provider
            kind_ext = {
                "ai-cadquery": "py",
                "ai-openscad": "scad",
            }
            if path.lower().endswith((".%s" % kind_ext[kind]).lower()):
                path = path.rsplit('.', 1)[0] + '.gen.' + kind_ext[kind]
            else:
                path += '.gen'
        if prj.add_part(kind, path, config):
            Path(path).touch()
