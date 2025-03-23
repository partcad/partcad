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
@pc.telemetry.tracer.start_as_current_span("list packages")
def cli(cli_ctx: CliContext, recursive: bool, package: str):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name

        with pc.logging.Process("ListPackages", package):
            # TODO-103: Show source (URL, PATH) of the package, probably use prettytable as well
            pkg_count = 0

            projects = ctx.get_all_packages()
            projects = sorted(projects, key=lambda p: p["name"])

            output = "PartCAD packages:\n"
            for project in projects:
                project_name = project["name"]

                if not recursive and package != project_name:
                    continue

                if recursive and not project_name.startswith(package):
                    continue

                line = "\t%s" % project_name
                padding_size = 60 - len(project_name)
                if padding_size < 4:
                    padding_size = 4
                line += " " * padding_size
                desc = project["desc"]
                if project.get("url"):
                    desc += f"\n{project['url']}"
                desc = desc.replace("\n", "\n" + " " * 68)
                line += "%s" % desc
                output += line + "\n"
                pkg_count = pkg_count + 1

            if pkg_count < 1:
                output += "\t<none>\n"
            pc.logging.info(output)
