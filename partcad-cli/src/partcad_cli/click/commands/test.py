#
# PartCAD, 2025
# OpenVMP, 2023-2024
#
# Author: Aleksandr Ilin (ailin@partcad.org)
# Created: Fri Nov 22 2024
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="Run tests on a part, assembly, or scene")
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively test all imported packages",
)
@click.option(
    "--filter",
    "-f",
    help="Only run tests that start with the given prefix",
    type=str,
    show_envvar=True,
    default=None,
)
@click.option(
    "--sketch",
    "-s",
    is_flag=True,
    show_envvar=True,
    help="The object is a sketch",
)
@click.option(
    "--interface",
    "-i",
    is_flag=True,
    show_envvar=True,
    help="The object is an interface",
)
@click.option(
    "--assembly",
    "-a",
    is_flag=True,
    show_envvar=True,
    help="The object is an assembly",
)
@click.option(
    "--scene",
    "-S",
    is_flag=True,
    show_envvar=True,
    help="The object is a scene",
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to test"
@click.pass_obj
def cli(cli_ctx, package, recursive, filter, sketch, interface, assembly, scene, object):
    run(
        cli_ctx,
        "test.run",
        {
            "package": package,
            "recursive": recursive,
            "filter": filter,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "object": object,
        },
        needs_context=True,
    )
