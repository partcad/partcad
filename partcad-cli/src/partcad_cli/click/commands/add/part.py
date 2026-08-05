#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from ...service import run

# TODO-93: @alexanderilyin: Make this optional and detect the kind from the PATH
PART_KINDS = [
    "cadquery",
    "build123d",
    "sdf",
    "scad",
    "step",
    "brep",
    "stl",
    "3mf",
    "obj",
]


@click.command(help="Add a part")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The part description.",
    required=False,
    show_envvar=True,
)
@click.argument("kind", type=click.Choice(PART_KINDS))
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, kind: str, path: str):
    """
    CLI command to add a part to the project without copying.
    """
    cli_ctx = click_ctx.obj

    file_path = Path(path)
    if not file_path.exists():
        raise click.UsageError(f"ERROR: The part file '{file_path}' does not exist.")

    # Absolute: the daemon runs detached, with a different working directory. It
    # reports the path back relative to the package that receives it, and
    # rejects a path that is not inside that package.
    params = {"obj_kind": "part", "kind": kind, "path": os.path.abspath(path)}
    package = click_ctx.parent.params.get("package")
    if package is not None:
        params["package"] = package
    if desc:
        params["desc"] = desc

    result = run(cli_ctx, "add.object", params, span_name="add part", needs_context=True)
    # No result means the daemon rejected the file (e.g. outside the package) and
    # already said why; do not follow that with a success line.
    if result and result.get("name"):
        click.echo(f"Part '{result['name']}' added to the project.")
