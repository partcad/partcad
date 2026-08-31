#
# PartCAD, 2025
# OpenVMP, 2023-2024
#
# Author: Aleksandr Ilin (ailin@partcad.org)
# Created: Fri Nov 22 2024
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ..service import run


# TODO-105: @alexanderilyin: Replace --scene, --interface, --assembly, --sketch with a single option --type
@click.command(help="Render a 2D projection of parts, assemblies, or scenes onto a plane")
@click.option(
    "-p",
    "--create-dirs",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-O",
    "--output-dir",
    help="Create artifacts in the given output directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    show_envvar=True,
)
@click.option(
    "-t",
    "--format",
    help="The type of file to render: readme, pdf, html, svg, png, jpeg, dxf, or any type a package implements itself",
    type=str,
    show_envvar=True,
)
@click.option(
    "--ignore-manufacturability",
    help="Generate the assembly instruction book even if the assembly is not manufacturable",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from",
    type=str,
    show_envvar=True,
)
@click.option(
    "-e",
    "--options-package",
    help="Package to read the export/render options from, in addition to the object's own package",
    type=str,
    show_envvar=True,
)
@click.option(
    "-r",
    "--recursive",
    help="Recursively test all imported packages",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-i",
    "--interface",
    help="The object is an interface",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    help="The object is a scene",
    is_flag=True,
    show_envvar=True,
)
# Ports and interfaces are not geometry, so they are invisible in a projection
# unless asked for. These three ask.
@click.option(
    "--with-ports",
    help="Draw a labelled coordinate frame at every port of the object (and, for an assembly, of everything in it)",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--with-interfaces",
    help="Draw the boundary of every port, labelled with the interface it belongs to",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--with-all",
    help="Draw both the ports and the interfaces",
    is_flag=True,
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # Part (default), assembly or scene to test
@click.pass_obj
def cli(
    cli_ctx,
    create_dirs,
    output_dir,
    format,
    ignore_manufacturability,
    package,
    options_package,
    recursive,
    sketch,
    interface,
    assembly,
    scene,
    with_ports,
    with_interfaces,
    with_all,
    object,
):
    run(
        cli_ctx,
        "render.objects",
        {
            "label": "Render",
            "create_dirs": create_dirs,
            # Resolve to absolute so artifacts land in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "format": format,
            "ignore_manufacturability": ignore_manufacturability,
            "package": package,
            "options_package": options_package,
            "recursive": recursive,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "with_ports": with_ports,
            "with_interfaces": with_interfaces,
            "with_all": with_all,
            "object": object,
        },
        needs_context=True,
    )
