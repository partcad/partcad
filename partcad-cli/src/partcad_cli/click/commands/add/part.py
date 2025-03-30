#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.actions.part import add_part_action
from ...cli_context import CliContext


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
            "sdf",
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
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, kind: str, provider: str | None, path: str):
    """
    CLI command to add a part to the project without copying.
    """
    package = click_ctx.parent.params["package"]
    cli_ctx: CliContext = click_ctx.obj

    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name  # '//' may end up having a different name

        file_path = Path(path)
        if not file_path.exists():
            raise click.UsageError(f"ERROR: The part file '{file_path}' does not exist.")

        config = {}
        if desc:
            config["desc"] = desc
        if provider:
            config["provider"] = provider

        # pc.logging.Process() is done inside "add_part_action"
        add_part_action(package_obj, kind, path, config)
        click.echo(f"Part '{Path(path).stem}' added to the project.")
