import rich_click as click  # import click


@click.command(
    help="- Render the selected or all parts, assemblies and scenes in this package"
)
def cli():
    pass


#
# OpenVMP, 2023-2024
#
# Author: Roman Kuzmenko
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import argparse

import partcad.logging as pc_logging
import partcad.utils as pc_utils


def cli_help_test(subparsers: argparse.ArgumentParser):
    parser_test = subparsers.add_parser(
        "test",
        help="Render the selected or all parts, assemblies and scenes in this package",
    )

    parser_test.add_argument(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        dest="package",
        default="",
    )
    parser_test.add_argument(
        "-r",
        help="Recursively test all imported packages",
        dest="recursive",
        action="store_true",
    )

    group_type = parser_test.add_mutually_exclusive_group(required=False)
    group_type.add_argument(
        "-s",
        help="The object is a sketch",
        dest="sketch",
        action="store_true",
    )
    group_type.add_argument(
        "-i",
        help="The object is an interface",
        dest="interface",
        action="store_true",
    )
    group_type.add_argument(
        "-a",
        help="The object is an assembly",
        dest="assembly",
        action="store_true",
    )
    group_type.add_argument(
        "-S",
        help="The object is a scene",
        dest="scene",
        action="store_true",
    )

    parser_test.add_argument(
        "object",
        help="Part (default), assembly or scene to test",
        type=str,
        nargs="?",
    )


def cli_test(args, ctx):
    package = args.package if args.package is not None else ""
    if args.recursive:
        start_package = pc_utils.get_child_project_path(
            ctx.get_current_project_path(), package
        )
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
        if not args.object is None:
            if not ":" in args.object:
                args.object = ":" + args.object
            args.package, args.object = pc_utils.resolve_resource_path(
                ctx.get_current_project_path(), args.object
            )

        prj = ctx.get_project(package)
        if args.object is None:
            # Test all parts and assemblies in this project
            prj.test()
        else:
            # Test the requested part or assembly
            if args.sketch:
                shape = prj.get_sketch(args.object)
            elif args.interface:
                shape = prj.get_interface(args.object)
            elif args.assembly:
                shape = prj.get_assembly(args.object)
            else:
                shape = prj.get_part(args.object)

            shape.test()
