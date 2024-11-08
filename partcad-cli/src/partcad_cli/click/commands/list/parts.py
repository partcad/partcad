import rich_click as click
import partcad as pc
import time


@click.command()
@click.option(
    "-u",
    "used_by",
    help="Only process objects used by the given assembly or scene.",
    type=str,
    required=False,
)
@click.option(
    "-r",
    "recursive",
    is_flag=True,
    help="Recursively process all imported packages",
)
@click.argument("package", type=str, required=False)
@click.pass_obj
def cli(ctx, used_by, recursive, package):
    """
    List available parts

    \b
    ----------------
    PACKAGE: Package to retrieve the object from
    """
    part_count = 0
    part_kinds = 0

    if used_by is not None:
        pc.logging.info("Instantiating %s..." % used_by)
        ctx.get_assembly(used_by)
    else:
        ctx.get_all_packages()

    # TODO: @openvmp: remove the following workaround after replacing 'print'
    # with corresponding logging calls
    time.sleep(2)

    output = "PartCAD parts:\n"
    for project_name in ctx.projects:
        if not recursive and package is not None and package != project_name:
            continue

        if recursive and package is not None and not project_name.startswith(package):
            continue

        if recursive and package is None and not project_name.startswith(ctx.get_current_project_path()):
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
    pc.logging.info(output)
