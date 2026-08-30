#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run

# The scene types that are a file in the package. 'alias' and 'enrich' are
# deliberately absent: each is a reference to another scene, not a file to
# point at.
SCENE_KINDS = ["assy", "world"]


@click.command(help="Add a scene")
@click.argument("kind", type=click.Choice(SCENE_KINDS))  # help="Type of the scene"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, kind: str, path: str):
    """Declare an existing file in the package as a scene.

    The file is used where it lies and is not converted: a Gazebo world added
    this way stays a Gazebo world, and what it holds - its models' links -
    becomes parts of the package as it is read. Use 'pc import scene' to turn
    one into PartCAD's own objects instead.

    An ASSY file declared here is read as a *scene* rather than as an assembly:
    it states where things are, and 'how:' is not allowed in it (see
    docs/source/assy.rst).
    """
    cli_ctx = click_ctx.obj

    # Absolute for the daemon (see add/part.py); reported back package-relative.
    params = {"obj_kind": "scene", "kind": kind, "path": os.path.abspath(path)}
    package = click_ctx.parent.params.get("package")
    if package is not None:
        params["package"] = package

    run(cli_ctx, "add.object", params, span_name="add scene", needs_context=True)
