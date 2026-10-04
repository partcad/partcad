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

from .. import fast_only
from ..exclude import exclude_option, exclude_params
from ..link_filter import filter_option, filter_params
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
@fast_only.option()
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
    "--port",
    "ports",
    help=(
        "Draw only this port rather than every one of them, and repeat the option for several. "
        "Named the way the log names it: the port's own name for a port of the object, "
        "and the path of nodes then the port for one inside an assembly ('bolt:thread-m8'). "
        "It says which ports, not that any are drawn, so it goes with one of the three options above"
    ),
    type=str,
    multiple=True,
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
@exclude_option
@filter_option
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
    fast_only,
    sketch,
    interface,
    assembly,
    scene,
    with_ports,
    with_interfaces,
    with_all,
    with_internals,
    exclude,
    ports,
    link_filter,
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
            "fast_only": fast_only,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "with_ports": with_ports,
            "with_interfaces": with_interfaces,
            "with_all": with_all,
            "with_internals": with_internals,
            # Empty is "every port the overlay found", which is what the three
            # options above meant on their own before this existed.
            "ports": list(ports) or None,
            "object": object,
            **exclude_params(exclude),
            **filter_params(link_filter),
        },
        needs_context=True,
    )
