#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext


# TODO-92: @alexanderilyin: Patch rich_click to support help strings for arguments
@click.command(help="Add a dependency")
@click.argument("alias", type=str)  # help="Alias to be used to reference the package"
@click.argument("location", type=str)  # help="Path or URL to the package"
@click.pass_context
def cli(click_ctx: click.Context, alias: str, location: str):
    package = click_ctx.parent.params["package"]
    cli_ctx: CliContext = click_ctx.obj

    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name

        with pc.logging.Process("AddDep", package):
            package_obj.add_import(alias, location)
