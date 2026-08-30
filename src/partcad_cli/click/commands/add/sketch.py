#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.actions.add import add_object_from_url_async, looks_like_url

from ...cli_context import CliContext


@click.command(help="Add a sketch from a file or a URL")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The sketch description.",
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
        ]
    ),
    # help="Type of the sketch",
)
@click.argument("path", type=str)  # help="Path to the file, or a URL to fetch it from"
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, kind: str, path: str):
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

        config = {}
        if desc:
            config["desc"] = desc

        if looks_like_url(path):
            # Fetched once so the declaration can be pinned with the 'fileHash'
            # of what came back; the fetched copy is not kept (see
            # 'partcad.actions.add'). In this process rather than through the
            # daemon, because everything else this command does is here too.
            try:
                name = asyncio.run(
                    add_object_from_url_async(ctx, package_obj, "sketches", path, kind=kind, config=config)
                )
            except Exception as e:  # pylint: disable=broad-except
                raise click.UsageError(f"ERROR: Failed to fetch '{path}': {e}")
            click.echo(f"Sketch '{name}' added to the project.")
            return

        with pc.logging.Process("AddSketch", package):
            if package_obj.add_sketch(kind, path, config):
                Path(path).touch()
