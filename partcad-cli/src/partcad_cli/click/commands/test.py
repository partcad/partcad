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

from partcad.test.all import tests as all_tests


async def cli_test_async(ctx, packages, filter_prefix, sketch, interface, assembly, scene, object):
    """
    TODO-118: @alexanderilyin: Add scene support
    """
    tasks = []

    tests_to_run = all_tests()
    if filter_prefix:
        tests_to_run = list(filter(lambda t: t.name.startswith(filter_prefix), tests_to_run))
        logging.debug(f"Running tests with prefix {filter_prefix}")

    for package in packages:
        if object:
            if ":" not in object:
                object = ":" + object
            package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), object)

        prj = ctx.get_project(package)
        if not object:
            # Test all parts and assemblies in this project
            tasks.append(prj.test_log_wrapper_async(ctx, tests=tests_to_run))
        elif interface:
            # Test the requested interface
            shape = prj.get_interface(object)
            if shape is None:
                logging.error(f"{object} is not found")
            else:
                tasks.append(shape.test_async())
        else:
            # Test the requested part or assembly
            if sketch:
                shape = prj.get_sketch(object)
            elif assembly:
                shape = prj.get_assembly(object)
            else:
                shape = prj.get_part(object)

            if shape is None:
                logging.error(f"{object} is not found")
            else:
                tasks.extend([t.test_log_wrapper(ctx, shape) for t in tests_to_run])

    await asyncio.gather(*tasks)


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
def cli(ctx, package, recursive, filter, sketch, interface, assembly, scene, object):
    package = ctx.get_project(package).name
    with logging.Process("Test", package):
        if recursive:
            start_package = ctx.get_project_abs_path(package)
            all_packages = ctx.get_all_packages(start_package)
            if ctx.stats_git_ops:
                logging.info(f"Git operations: {ctx.stats_git_ops}")
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]

        asyncio.run(
            cli_test_async(
                ctx,
                packages,
                filter_prefix=filter,
                sketch=sketch,
                interface=interface,
                assembly=assembly,
                scene=scene,
                object=object,
            )
        )
