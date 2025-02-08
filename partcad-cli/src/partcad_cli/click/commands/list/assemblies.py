import rich_click as click
from partcad import logging as pc_logging
from partcad.context import Context


@click.command(help="List available assemblies")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx: Context, recursive: bool, package: str) -> None:
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc_logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with pc_logging.Process("ListAssemblies", package):
        assy_kinds = 0

        ctx.get_all_packages()

        output = "PartCAD assemblies:\n"
        for project_name in ctx.projects:
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for assy_name, assy in project.assemblies.items():
                line = "\t"
                if recursive:
                    line += f"{project_name}"
                    line += " " + " " * (35 - len(project_name))
                line += f"{assy_name}"
                line += " " + " " * (35 - len(assy_name))

                desc = assy.desc if assy.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (84 if recursive else 44))
                line += f"{desc}"
                output += line + "\n"
                assy_kinds = assy_kinds + 1

        if assy_kinds > 0:
            output += f"Total: {assy_kinds}\n"
        else:
            output += "\t<none>\n"
        pc_logging.info(output)
