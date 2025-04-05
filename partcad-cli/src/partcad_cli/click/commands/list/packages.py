#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext

"""List Packages command.

It shows the packages that have at least one sketch, part, or assembly.
The primary purpose of this interface is to feed user interfaces like IDEs with the list of packages that are worth
showing.
When no recursion in requested, it shows the current package if and only if it has any parts, sketches, or assemblies.
"""


@click.command(help="List imported packages")
@click.option("-r", "--recursive", is_flag=True, help="Recursively process all imported packages")
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
@pc.telemetry.start_as_current_span("list packages")
def cli(cli_ctx: CliContext, recursive: bool, package: str):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name  # '//' may end up having a different name

        with pc.logging.Process("ListPackages", package):
            # TODO-103: Show source (URL, PATH) of the package, probably use prettytable as well
            pkg_count = 0

            if recursive:
                all_packages = ctx.get_all_packages(parent_name=package, has_stuff=True)
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            output = "PartCAD packages:\n"
            for project_name in packages:
                project = ctx.projects[project_name]

                line = "\t%s" % project_name
                padding_size = 60 - len(project_name)
                if padding_size < 4:
                    padding_size = 4
                line += " " * padding_size
                desc = project.desc
                if hasattr(project, "url"):
                    desc += f"\n{project.url}"
                desc = desc.replace("\n", "\n" + " " * 68)
                line += "%s" % desc
                output += line + "\n"
                pkg_count = pkg_count + 1

            if pkg_count < 1:
                output += "\t<none>\n"
            pc.logging.info(output)
