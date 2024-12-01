#
# OpenVMP, 2023-2024
#
# Author: Aleksandr Ilin (ailin@partcad.org)
# Created: Fri Nov 22 2024
#
# Licensed under Apache License, Version 2.0.
#


import rich_click as click
import partcad.utils as pc_utils


@click.command()
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
@click.pass_obj
@click.argument("object", type=str)
def cli(ctx, package, recursive, sketch, interface, assembly, scene, object):
    """
    Render the selected or all parts, assemblies and scenes in this package

    \b
    ----------------
    OBJECT: Part (default), assembly or scene to test
    """

    package = package if package is not None else ""
    if recursive:
        start_package = pc_utils.get_child_project_path(ctx.get_current_project_path(), package)
        all_packages = ctx.get_all_packages(start_package)
        packages = list(
            map(
                lambda p: p["name"],
                list(all_packages),
            )
        )
    else:
        packages = [package]

    for package in packages:
        if not object is None:
            if not ":" in object:
                object = ":" + object
            package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), object)

        prj = ctx.get_project(package)
        if object is None:
            # Test all parts and assemblies in this project
            prj.test()
        else:
            # Test the requested part or assembly
            if sketch:
                shape = prj.get_sketch(object)
            elif interface:
                shape = prj.get_interface(object)
            elif assembly:
                shape = prj.get_assembly(object)
            else:
                shape = prj.get_part(object)

            shape.test()
