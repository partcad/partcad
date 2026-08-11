#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ..service import run


@click.command(help="Export 3D view of parts, assemblies, or scenes in the package")
@click.option(
    "-p",
    "--create-dirs",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
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
    help="The type of file to export",
    type=click.Choice(
        [
            "step",
            "brep",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
            "iges",
            "urdf",
        ]
    ),
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from",
    type=str,
)
@click.option(
    "-r",
    "--recursive",
    help="Recursively test all imported packages",
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
    create_dirs,
    output_dir,
    format,
    package: str,
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
            "create_dirs": create_dirs,
            # Resolve to absolute so artifacts land in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "format": format,
            "package": package,
            "recursive": recursive,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "object": object,
        },
        needs_context=True,
    )
