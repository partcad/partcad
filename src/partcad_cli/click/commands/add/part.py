#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from partcad_utils.utils import looks_like_url

from ...service import run

# TODO-93: @alexanderilyin: Make this optional and detect the kind from the PATH
PART_KINDS = [
    "cadquery",
    "build123d",
    "chili3d",
    "sdf",
    "scad",
    "step",
    "brep",
    "stl",
    "3mf",
    "obj",
]


@click.command(help="Add a part from a file or a URL")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The part description.",
    required=False,
    show_envvar=True,
)
@click.argument("kind", type=click.Choice(PART_KINDS))
@click.argument("path", type=str)  # help="Path to the file, or a URL to fetch it from"
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, kind: str, path: str):
    """
    CLI command to add a part to the project without copying.

    PATH is a file the package already has, or an http(s) URL. A URL is fetched
    once so that the declaration can be pinned with the 'fileHash' of what came
    back; the fetched copy is not kept (see 'partcad.actions.add').
    """
    cli_ctx = click_ctx.obj

    params = {"obj_kind": "part", "kind": kind}
    if looks_like_url(path):
        params["url"] = path
    else:
        file_path = Path(path)
        if not file_path.exists():
            raise click.UsageError(f"ERROR: The part file '{file_path}' does not exist.")
        # Absolute: the daemon runs detached, with a different working directory.
        # It reports the path back relative to the package that receives it, and
        # rejects a path that is not inside that package.
        params["path"] = os.path.abspath(path)
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
