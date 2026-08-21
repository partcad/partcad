#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run

# The assembly types that are a file in the package. 'alias' is deliberately
# absent: it is a reference to another assembly, not a file to point at.
ASSEMBLY_KINDS = ["assy", "urdf"]


@click.command(help="Add an assembly")
@click.argument("kind", type=click.Choice(ASSEMBLY_KINDS))  # help="Type of the assembly"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, kind: str, path: str):
    """Declare an existing file in the package as an assembly.

    The file is used where it lies and is not converted: a URDF added this way
    stays a URDF, and its links become parts of the package as it is read. Use
    'pc import assembly' to turn one into PartCAD's own objects instead.
    """
    cli_ctx = click_ctx.obj

    # Absolute for the daemon (see add/part.py); reported back package-relative.
    params = {"obj_kind": "assembly", "kind": kind, "path": os.path.abspath(path)}
    package = click_ctx.parent.params.get("package")
    if package is not None:
        params["package"] = package

    run(cli_ctx, "add.object", params, span_name="add assembly", needs_context=True)
