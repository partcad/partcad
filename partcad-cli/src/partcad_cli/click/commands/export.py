#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ..cli_context import CliContext


@click.command(help="Export 3D view of parts, assemblies, or scenes in the package")
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
            "step",
            "brep",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
            "iges",
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
def cli(
    cli_ctx: CliContext,
    create_dirs,
    output_dir,
    format,
    package: str,
    recursive,
    sketch,
    interface,
    assembly,
    scene,
    object,
):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return

        with pc.logging.Process("Export", package):
            ctx.option_create_dirs = create_dirs
            if recursive:
                all_packages = ctx.get_all_packages(package)
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            for package in packages:
                if not object is None:
                    package, object = pc.utils.resolve_resource_path(ctx.get_current_project_path() + package, object)

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

                    prj: pc.Project = ctx.get_project(package)
                    prj.render(
                        sketches=sketches,
                        interfaces=interfaces,
                        parts=parts,
                        assemblies=assemblies,
                        format=format,
                        output_dir=output_dir,
                    )
