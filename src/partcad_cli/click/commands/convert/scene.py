#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run

# Deliberately not a 'click.Choice'. A scene converts between 'assy' -- PartCAD's
# own way of saying where things are -- and any file format that says the same
# thing, and which formats those are is a fact about the workspace's packages
# rather than about this command: a Gazebo world and an MJCF model both come
# from a plugin package now ('sim-gazebo:world', 'sim-mujoco:mjcf'), and a
# fixed list here could only ever be out of date. The daemon resolves the name
# against the package graph and says what is wrong with one that does not
# resolve.
#
# Like an assembly, a scene is not a single file that can be handed to an
# exporter: converting one rewrites the package around it, which is why
# 'pc adhoc convert' has no equivalent.


@click.command(help="Convert a scene between ASSY and a file format that expresses an arrangement.")
@click.argument("object_name", type=str, required=True)
@click.option(
    "-t",
    "--target-format",
    help="Target conversion format: 'assy', or a format a package reads as a scene "
    "(for example 'sim-gazebo:world' or 'sim-mujoco:mjcf').",
    type=str,
    required=True,
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the scene from",
    type=str,
)
@click.option(
    "-O",
    "--output-dir",
    help="Output directory for the converted files. Defaults to the package directory.",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option("--dry-run", help="Simulate conversion without making any changes.", is_flag=True)
@click.pass_obj
def cli(cli_ctx, object_name: str, target_format: str, package: str, output_dir: str, dry_run: bool):
    """CLI command to convert a scene to a new format.

    Converting to a file format writes that file and a mesh for every distinct
    shape in the scene. Converting to ``assy`` copies every shape the file
    places into the package as a part of its own and writes an ``.assy`` that
    places them.
    """
    run(
        cli_ctx,
        "convert.object",
        {
            "kind": "scene",
            "object_name": object_name,
            "target_format": target_format,
            "package": package,
            # Resolve to absolute so output lands in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "dry_run": dry_run,
        },
        needs_context=True,
    )
