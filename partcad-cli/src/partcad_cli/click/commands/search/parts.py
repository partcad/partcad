import os
import yaml
import rich_click as click

from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="Search parts by keyword")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter parts using the specified keyword",
    type=str,
    required=True,
)
@click.argument("package", type=str, required=False, default=".")  # help='Package to search the object in'
@click.pass_obj
def cli(ctx: Context, recursive: bool, package: str, keyword: str) -> None:
    keyword = keyword.lower()
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("SearchParts", package):
        part_kinds = 0

        ctx.get_all_packages()

        output = f"PartCAD parts with '{keyword}' keyword:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            with open(os.path.join(project.path, 'partcad.yaml')) as f:
                prj_config = yaml.safe_load(f)

            if keyword and keyword in str(prj_config):
                for part_name, part in project.parts.items():
                    part_config = ""
                    if 'parts' in prj_config and part_name in prj_config['parts']:
                        part_config = str(prj_config['parts'][part_name]).lower()

                    if keyword not in part_config and keyword not in part_name:
                        continue

                    line = "\t"
                    if recursive:
                        line += "%s" % project_name
                        line += " " + " " * (35 - len(project_name))
                    line += "%s" % part_name
                    line += " " + " " * (35 - len(part_name))

                    desc = part.desc if part.desc is not None else ""
                    desc = desc.replace("\n", "\n" + " " * (84 if recursive else 44))
                    line += "%s" % desc
                    output += line + "\n"
                    part_kinds = part_kinds + 1

        if part_kinds > 0:
            output += "Matches: %d\n" % part_kinds
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
