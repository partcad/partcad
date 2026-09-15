#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run

# Deliberately not a 'click.Choice', for the reason 'convert/scene.py' is not
# one: a scene is 'assy' -- PartCAD's own way of saying where things are -- or
# any file format a package reads as one, and which formats those are is a fact
# about the workspace's packages rather than about this command. An engine's own
# scene format comes from that engine's plugin package ('sim-gazebo:world',
# 'sim-mujoco:mjcf'), so a fixed list here could only ever be out of date, and
# the one it used to hold ('world') no longer resolves on its own.
#
# The daemon resolves the name against the package graph and says what is wrong
# with one that does not resolve. 'alias' and 'enrich' are not scene *files* and
# are not added this way: each is a reference to another scene.


@click.command(help="Add a scene")
@click.argument("kind", type=str)  # help="Type of the scene: 'assy', or a format a package reads as a scene"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_context
def cli(click_ctx: click.Context, kind: str, path: str):
    """Declare an existing file in the package as a scene.

    The file is used where it lies and is not converted: a Gazebo world added
    this way ('pc add scene sim-gazebo:world warehouse.world') stays a Gazebo
    world, and what it holds - its models' links - becomes parts of the package
    as it is read. Use 'pc import scene' to turn one into PartCAD's own objects
    instead.

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
