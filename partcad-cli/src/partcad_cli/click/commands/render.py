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
import partcad.logging as logging


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
    help="The type of file to export",
    type=click.Choice(["readme", "svg", "png"]),
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
@click.argument("object", type=str, required=False)  # Part (default), assembly or scene to test
@click.pass_obj
def cli(ctx, create_dirs, output_dir, format, package, recursive, sketch, interface, assembly, scene, object):
    with logging.Process("Render", "this"):
        ctx.option_create_dirs = create_dirs
        package = package if package is not None else "."
        package_obj = ctx.get_project(package)
        if not package_obj:
            logging.error(f"Package {package} is not found")
            return
        package = package_obj.name
        if recursive:
            all_packages = ctx.get_all_packages(package)
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
                # TODO-107: @clairbee: it seems that resolve_resource_path() does not resolve the resource path correctly for -p
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
