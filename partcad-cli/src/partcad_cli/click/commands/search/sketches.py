import os
import yaml
import rich_click as click

from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="Search sketches by keyword")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter sketches using the specified keyword",
    type=str,
    required=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx: Context, recursive: bool, package: str, keyword: str) -> None:
    keyword = keyword.lower()
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name
    with pc_logging.Process("SearchSketches", package):
        sketch_kinds = 0

        ctx.get_all_packages()

        output = f"PartCAD sketches with '{keyword}' keyword:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            with open(os.path.join(project.path, 'partcad.yaml')) as f:
                prj_config = yaml.safe_load(f)

            if keyword and keyword in str(prj_config):
                for sketch_name, sketch in project.sketches.items():
                    sketch_config = ""
                    if 'sketches' in prj_config and sketch_name in prj_config['sketches']:
                        sketch_config = str(prj_config['sketches'][sketch_name]).lower()

                    if keyword not in sketch_config and keyword not in sketch_name:
                        continue

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
            output += "Matches: %d\n" % sketch_kinds
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
