import os
import yaml
import rich_click as click

from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="Search packages by keyword")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively search packages"
 )
@click.option(
    "-k",
    "--keyword",
    help="Search and filter packages using the specified keyword",
    type=str,
    required=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx: Context, recursive: bool, package: str, keyword: str) -> None:
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("SearchPackages", package):
        # TODO-103: Show source (URL, PATH) of the package, probably use prettytable as well
        pkg_count = 0

        projects = ctx.get_all_packages()
        projects = sorted(projects, key=lambda p: p["name"])

        output = f"PartCAD packages with '{keyword}' keyword:\n"
        for project in projects:
            project_name = project["name"]

            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            with open(os.path.join(ctx.projects[project_name].path, 'partcad.yaml')) as f:
                prj_config = yaml.safe_load(f)

            if keyword.lower() not in str(prj_config).lower():
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

        if pkg_count > 0:
            output += "Matches: %d\n" % pkg_count
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
