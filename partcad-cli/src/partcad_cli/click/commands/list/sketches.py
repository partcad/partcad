import rich_click as click
from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="List available sketches")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
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
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx: Context, recursive: bool, used_by: str | None, package: str):
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("ListSketches", package):
        sketch_count = 0
        sketch_kinds = 0

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

        output = "PartCAD sketches:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for sketch_name, sketch in project.sketches.items():
                if used_by is not None and sketch.count == 0:
                    continue

                line = "\t"
                if recursive:
                    line += "%s" % project_name
                    line += " " + " " * (35 - len(project_name))
                line += "%s" % sketch_name
                if used_by is not None:
                    sketch = project.sketches[sketch_name]
                    line += "(%d)" % sketch.count
                    sketch_count = sketch_count + sketch.count
                line += " " + " " * (35 - len(sketch_name))

                desc = sketch.desc if sketch.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                line += "%s" % desc
                output += line + "\n"
                sketch_kinds = sketch_kinds + 1

        if sketch_kinds > 0:
            if used_by is None:
                output += "Total: %d\n" % sketch_kinds
            else:
                output += "Total: %d sketches of %d kinds\n" % (
                    sketch_count,
                    sketch_kinds,
                )
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
