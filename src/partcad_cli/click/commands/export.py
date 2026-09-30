#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ..service import run


@click.command(
    help=(
        "Export 3D view of parts, assemblies, or scenes in the package. "
        "OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it"
    ),
)
@click.option(
    "-O",
    "--output-dir",
    help="Create artifacts in the given output directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option(
    "-t",
    "--format",
    help=(
        "The type of file to export: step, brep, stl, 3mf, threejs, obj, gltf, iges, urdf, world, "
        "or any type a package implements itself"
    ),
    type=str,
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
    type=str,
)
@click.option(
    "-e",
    "--options-package",
    help="Package to read the export/render options from, in addition to the object's own package",
    type=str,
)
@click.option(
    "-r",
    "--recursive",
    help="Recursively test all imported packages (older spelling of '<package>...')",
    is_flag=True,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
)
@click.option(
    "-i",
    "--interface",
    help="The object is an interface",
    is_flag=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly",
    is_flag=True,
)
@click.option(
    "-S",
    "--scene",
    help="The object is a scene",
    is_flag=True,
)
@click.argument("object", type=str, required=False)  # Part (default), assembly or scene to test
@click.pass_obj
def cli(
    cli_ctx,
    output_dir,
    format,
    package: str,
    options_package: str,
    recursive,
    sketch,
    interface,
    assembly,
    scene,
    object,
):
    run(
        cli_ctx,
        "render.objects",
        {
            "label": "Export",
            # Resolve to absolute so artifacts land in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "format": format,
            "package": package,
            "options_package": options_package,
            "recursive": recursive,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "object": object,
        },
        needs_context=True,
    )
