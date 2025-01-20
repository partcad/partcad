import rich_click as click
from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="List available parts")
@click.option(
    "-u",
    "--used_by",
    "used_by",
    help="Only process objects used by the given assembly or scene.",
    type=str,
    required=False,
    show_envvar=True,
)
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
def cli(ctx: Context, used_by: str | None, recursive: bool, package: str):
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("ListParts", package):
        part_count = 0
        part_kinds = 0

        if used_by is not None:
            pc_logging.info("Instantiating %s..." % used_by)
            try:
                target = ctx.get_assembly(used_by)
                if not target:
                    pc_logging.error(f"Assembly {used_by} is not found")
                    return
            except:
                pc_logging.error(f"Failed to instantiate the assembly {used_by}")
                return
        else:
            ctx.get_all_packages()

        output = "PartCAD parts:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for part_name, part in project.parts.items():
                if used_by is not None and part.count == 0:
                    continue

                line = "\t"
                if recursive:
                    line += "%s" % project_name
                    line += " " + " " * (35 - len(project_name))
                line += "%s" % part_name
                if used_by is not None:
                    part = project.parts[part_name]
                    line += "(%d)" % part.count
                    part_count = part_count + part.count
                line += " " + " " * (35 - len(part_name))

                desc = part.desc if part.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (84 if recursive else 44))
                line += "%s" % desc
                output += line + "\n"
                part_kinds = part_kinds + 1

        if part_kinds > 0:
            if used_by is None:
                output += "Total: %d\n" % part_kinds
            else:
                output += "Total: %d parts of %d kinds\n" % (part_count, part_kinds)
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
