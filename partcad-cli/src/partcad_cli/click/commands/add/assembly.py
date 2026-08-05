#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run


@click.command(help="Add an assembly")
@click.argument("kind", type=click.Choice(["assy"]))  # help="Type of the assembly"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, kind: str, path: str):
    cli_ctx = click_ctx.obj

    params = {"obj_kind": "assembly", "kind": kind, "path": os.path.abspath(path)}
    package = click_ctx.parent.params.get("package")
    if package is not None:
        params["package"] = package

    run(cli_ctx, "add.object", params, span_name="add assembly", needs_context=True)
