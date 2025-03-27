import os
import yaml
import rich_click as click

from partcad import logging
from partcad.logging import Process
from partcad.context import Context


@click.command(help="Search interfaces by keyword")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "-u",
    "--used_by",
    type=str,
    required=False,
    help="Only process objects used by the given assembly or scene.",
    show_envvar=True,
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter interfaces using the specified keyword",
    type=str,
    required=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx: Context, recursive: bool, used_by: str, package: str, keyword: str) -> None:
    keyword = keyword.lower()
    package_obj = ctx.get_project(package)
    if not package_obj:
        logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with Process("SearchInterfaces", package):
        interface_count = 0
        interface_kinds = 0

        if used_by is not None:
            logging.info(f"Instantiating {used_by}...")
            ctx.get_assembly(used_by)
        else:
            ctx.get_all_packages()

        output = f"PartCAD interfaces with '{keyword}' keyword:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            with open(os.path.join(project.path, 'partcad.yaml')) as f:
                prj_config = yaml.safe_load(f)

            if keyword and keyword in str(prj_config):
                for interface_name, interface in project.interfaces.items():
                    if used_by is not None and interface.count == 0:
                        continue

                    interface_config = ""
                    if 'interfaces' in prj_config and interface_name in prj_config['interfaces']:
                        interface_config = str(prj_config['interfaces'][interface_name]).lower()

                    if keyword not in interface_config and keyword not in interface_name:
                        continue

                    line = "\t"
                    if recursive:
                        line += f"{project_name}"
                        line += " " + " " * (35 - len(project_name))
                    line += f"{interface_name}"
                    if used_by is not None:
                        interface = project.get_interface(interface_name)
                        line += f"({interface.count})"
                        interface_count = interface_count + interface.count
                    line += " " + " " * (35 - len(interface_name))

                    desc = interface.desc if interface.desc is not None else ""
                    desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                    line += f"{desc}"
                    output += line + "\n"
                    interface_kinds = interface_kinds + 1

        if interface_kinds > 0:
            if used_by is None:
                output += f"Matches: {interface_kinds}\n"
            else:
                output += f"Matches: {interface_count} interfaces of {interface_kinds} kinds\n"
        else:
            output += "\t<none>\n"
        logging.info(output)
