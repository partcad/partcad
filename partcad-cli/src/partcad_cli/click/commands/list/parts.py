import rich_click as click
from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="List available parts")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(ctx: Context, recursive: bool, package: str) -> None:
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("ListParts", package):
        part_kinds = 0

        ctx.get_all_packages()

        output = "PartCAD parts:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for part_name, part in project.parts.items():
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
            output += "Total: %d\n" % part_kinds
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
