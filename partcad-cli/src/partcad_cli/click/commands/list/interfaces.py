#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext


@click.command(help="List available interfaces")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return

        with pc.logging.Process("ListInterfaces", package):
            interface_kinds = 0

            if recursive:
                all_packages = ctx.get_all_packages()
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            output = "PartCAD interfaces:\n"
            for project_name in packages:
                if not recursive and package != project_name:
                    continue

                if recursive and not project_name.startswith(package):
                    continue

                project: pc.Project = ctx.projects[project_name]

                for interface_name, interface in project.interfaces.items():

                    line = "\t"
                    if recursive:
                        line += f"{project_name}"
                        line += " " + " " * (35 - len(project_name))
                    line += f"{interface_name}"
                    line += " " + " " * (35 - len(interface_name))

                    desc = interface.desc if interface.desc is not None else ""
                    desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                    line += f"{desc}"
                    output += line + "\n"
                    interface_kinds = interface_kinds + 1

            if interface_kinds > 0:
                output += f"Total: {interface_kinds}\n"
            else:
                output += "\t<none>\n"
            pc.logging.info(output)
