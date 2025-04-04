#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Add a sketch")
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
            "dxf",
            "svg",
            "basic",
            "ai-cadquery",
            "ai-openscad",
        ]
    ),
    # help="Type of the sketch",
)
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, kind: str, provider: str | None, path: str):
    package = click_ctx.parent.params["package"]
    cli_ctx: CliContext = click_ctx.obj

    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return

        with pc.logging.Process("AddSketch", package):
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
                    path = path.rsplit(".", 1)[0] + ".gen." + kind_ext[kind]
                else:
                    path += ".gen"
            if package_obj.add_sketch(kind, path, config):
                Path(path).touch()
