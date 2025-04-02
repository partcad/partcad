#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Add an assembly")
@click.argument("kind", type=click.Choice(["assy"]))  # help="Type of the assembly"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, kind: str, path: str):
    package = click_ctx.parent.params["package"]
    cli_ctx: CliContext = click_ctx.obj

    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name

        with pc.logging.Process("AddAssy", package):
            if package_obj.add_assembly(kind, path):
                Path(path).touch()
