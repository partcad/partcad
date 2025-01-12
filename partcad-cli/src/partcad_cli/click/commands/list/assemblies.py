import rich_click as click
from partcad import logging
from partcad.logging import Process


@click.command(help="List available assemblies")
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
def cli(ctx, recursive, used_by, package):
    package = ctx.get_project(package).name

    with Process("ListAssy", package):
        assy_count = 0
        assy_kinds = 0

        if used_by is not None:
            logging.info(f"Instantiating {used_by}...")
            # TODO(clairbee): do not call it twice in 'list all'
            ctx.get_assembly(used_by)
        else:
            ctx.get_all_packages()

        output = "PartCAD assemblies:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for assy_name, assy in project.assemblies.items():
                if used_by is not None and assy.count == 0:
                    continue

                line = "\t"
                if recursive:
                    line += f"{project_name}"
                    line += " " + " " * (35 - len(project_name))
                line += f"{assy_name}"
                if used_by is not None:
                    assy = project.assemblies[assy_name]
                    line += "(%d)" % assy.count
                    assy_count = assy_count + assy.count
                line += " " + " " * (35 - len(assy_name))

                desc = assy.desc if assy.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (84 if recursive else 44))
                line += f"{desc}"
                output += line + "\n"
                assy_kinds = assy_kinds + 1

        if assy_kinds > 0:
            if used_by is None:
                output += f"Total: {assy_kinds}\n"
            else:
                output += f"Total: {assy_count} assemblies of {assy_kinds} kinds\n"
        else:
            output += "\t<none>\n"
        logging.info(output)
