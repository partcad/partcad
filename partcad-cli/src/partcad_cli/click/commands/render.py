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
import partcad.logging as pc_logging


@click.command(help="Generate a rendered view of parts, assemblies, or scenes in the package")
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
            "readme",
            "svg",
            "png",
            "step",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
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
def cli(ctx, create_dirs, output_dir, format, package, recursive, sketch, interface, assembly, scene, object):
    with pc_logging.Process("Render", "this"):
        ctx.option_create_dirs = create_dirs
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
                # TODO: @clairbee: it seems that resolve_resource_path() does not resolve the resource path correctly for -p
                package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path() + package, object)

            if object is None:
                # Render all parts and assemblies configured to be auto-rendered in this project
                ctx.render(
                    project_path=package,
                    format=format,
                    output_dir=output_dir,
                )
            else:
                # Render the requested part or assembly
                sketches = []
                interfaces = []
                parts = []
                assemblies = []
                if sketch:
                    sketches.append(object)
                elif interface:
                    interfaces.append(object)
                elif assembly:
                    assemblies.append(object)
                else:
                    parts.append(object)

                prj = ctx.get_project(package)
                prj.render(
                    sketches=sketches,
                    interfaces=interfaces,
                    parts=parts,
                    assemblies=assemblies,
                    format=format,
                    output_dir=output_dir,
                )


#
# OpenVMP, 2023-2024
#
# Author: Roman Kuzmenko
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import argparse
import asyncio

import partcad.logging as pc_logging
import partcad.utils as pc_utils


def cli_help_render(subparsers: argparse.ArgumentParser):
    parser_render = subparsers.add_parser(
        "render",
        help="Generate a rendered view of parts, assemblies, or scenes in the package",
    )
    parser_render.add_argument(
        "-p",
        help="Create the neccessary directory structure if it is missing",
        dest="create_dirs",
        action="store_true",
    )
    parser_render.add_argument(
        "-O",
        help="Create artifacts in the given output directory",
        dest="output_dir",
        type=str,
        nargs="?",
    )
    parser_render.add_argument(
        "-t",
        help="The type of file to export",
        dest="format",
        type=str,
        nargs="?",
        choices=[
            "readme",
            "svg",
            "png",
            "step",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
        ],
    )

    parser_render.add_argument(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        dest="package",
        default="",
    )
    parser_render.add_argument(
        "-r",
        help="Recursively render all imported packages",
        dest="recursive",
        action="store_true",
    )

    group_type = parser_render.add_mutually_exclusive_group(required=False)
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

    parser_render.add_argument(
        "object",
        help="Part (default), assembly or scene to render",
        type=str,
        nargs="?",
    )


async def cli_render_async(args, ctx, packages):
    tasks = []
    for package in packages:
        if not args.object is None:
            if not ":" in args.object:
                args.object = ":" + args.object
            args.package, args.object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), args.object)

        if args.object is None:
            # Render all parts and assemblies configured to be auto-rendered in this project
            tasks.append(
                ctx.render_async(
                    project_path=package,
                    format=args.format,
                    output_dir=args.output_dir,
                )
            )
        else:
            # Render the requested part or assembly
            sketches = []
            interfaces = []
            parts = []
            assemblies = []
            if args.sketch:
                sketches.append(args.object)
            elif args.interface:
                interfaces.append(args.object)
            elif args.assembly:
                assemblies.append(args.object)
            else:
                parts.append(args.object)

            prj = ctx.get_project(package)
            if prj is None:
                pc_logging.error("%s is not found" % package)
            else:
                tasks.append(
                    prj.render(
                        sketches=sketches,
                        interfaces=interfaces,
                        parts=parts,
                        assemblies=assemblies,
                        format=args.format,
                        output_dir=args.output_dir,
                    )
                )
    await asyncio.gather(*tasks)


def cli_render(args, ctx):
    ctx.option_create_dirs = args.create_dirs

    package = args.package if args.package is not None else ""
    if args.recursive:
        start_package = ctx.get_project_abs_path(package)
        all_packages = ctx.get_all_packages(start_package)
        packages = list(
            map(
                lambda p: p["name"],
                list(all_packages),
            )
        )
    else:
        packages = [package]

    asyncio.run(cli_render_async(args, ctx, packages))
