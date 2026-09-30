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
from ..viewport import viewport_options, viewport_params


# TODO-105: @alexanderilyin: Replace --scene, --interface, --assembly, --sketch with a single option --type
@click.command(
    help=(
        "Render a 2D projection of parts, assemblies, or scenes onto a plane. "
        "OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it"
    ),
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
@viewport_options
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
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
    help="Recursively test all imported packages (older spelling of '<package>...')",
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
# unless asked for. These four ask.
@click.option(
    "--with-ports",
    help="Draw a labelled coordinate frame at every port of the object",
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
@click.option(
    "--with-internals",
    help=(
        "Say how deep the three above reach rather than asking for a drawing of its own: with any of them, "
        "the ports of everything inside an assembly are drawn as well as the ones it externalizes, "
        "which is how a connection that went wrong is found"
    ),
    is_flag=True,
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # Part (default), assembly or scene to test
@click.pass_obj
def cli(
    cli_ctx,
    output_dir,
    format,
    ignore_manufacturability,
    view,
    viewport_origin,
    viewport_up,
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
    with_internals,
    object,
):
    run(
        cli_ctx,
        "render.objects",
        {
            "label": "Render",
            # Resolve to absolute so artifacts land in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "format": format,
            "ignore_manufacturability": ignore_manufacturability,
            **viewport_params(view, viewport_origin, viewport_up),
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
            "with_internals": with_internals,
            "object": object,
        },
        needs_context=True,
    )
