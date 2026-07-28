#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext


@click.command(help="List available sketches")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name  # '//' may end up having a different name

        with pc.logging.Process("ListSketches", package):
            sketch_kinds = 0

            if recursive:
                all_packages = ctx.get_all_packages(parent_name=package, has_stuff=True)
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            output = "PartCAD sketches:\n"
            for project_name in packages:
                project = ctx.projects[project_name]

                for sketch_name, sketch in project.sketches.items():
                    line = "\t"
                    if recursive:
                        line += "%s" % project_name
                        line += " " + " " * (35 - len(project_name))
                    line += "%s" % sketch_name
                    line += " " + " " * (35 - len(sketch_name))

                    desc = sketch.desc if sketch.desc is not None else ""
                    desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                    line += "%s" % desc
                    output += line + "\n"
                    sketch_kinds = sketch_kinds + 1

            if sketch_kinds > 0:
                output += "Total: %d\n" % sketch_kinds
            else:
                output += "\t<none>\n"
            pc.logging.info(output)
