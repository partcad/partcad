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
from partcad import logging as logging
import asyncio


async def cli_test_async(ctx, packages, sketch, interface, assembly, scene, object):
    """
    TODO-118: @alexanderilyin: Add scene support
    """
    tasks = []
    for package in packages:
        if object is not None:
            if ":" not in object:
                object = ":" + object
            package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), object)

        prj = ctx.get_project(package)
        if object is None:
            # Test all parts and assemblies in this project
            tasks.append(prj.test_async())
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

            if shape is None:
                logging.error(f"{object} is not found")
            else:
                tasks.append(shape.test_async())

    await asyncio.gather(*tasks)


@click.command(help="Run tests on a part, assembly, or scene")
@click.option("--package", "-P", help="Package to retrieve the object from", type=str, default="")
@click.option("--recursive", "-r", help="Recursively test all imported packages", is_flag=True)
@click.option("--sketch", "-s", help="The object is a sketch", is_flag=True)
@click.option("--interface", "-i", help="The object is an interface", is_flag=True)
@click.option("--assembly", "-a", help="The object is an assembly", is_flag=True)
@click.option("--scene", "-S", help="The object is a scene", is_flag=True)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to test"
@click.pass_obj
def cli(ctx, package, recursive, sketch, interface, assembly, scene, object):
    with logging.Process("Test", "this"):
        package = package if package is not None else ""
        if recursive:
            start_package = ctx.get_project_abs_path(package)
            all_packages = ctx.get_all_packages(start_package)
            if ctx.stats_git_ops:
                logging.info(f"Git operations: {ctx.stats_git_ops}")
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]

        asyncio.run(cli_test_async(ctx, packages, sketch, interface, assembly, scene, object))
