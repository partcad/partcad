import rich_click as click
from partcad import logging
from partcad.logging import Process


@click.command(help="List available providers")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx, recursive, package):
    package_obj = ctx.get_project(package)
    if not package_obj:
        logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with Process("ListProviders", package):
        provider_kinds = 0

        if recursive:
            projects = ctx.get_all_packages(package if package != "." else None)
            projects = sorted(map(lambda p: p["name"], projects))
        else:
            projects = [package]

        output = "PartCAD providers:\n"
        for project_name in projects:
            logging.info(f"Processing project {project_name}")
            if not recursive and package != project_name:
                continue

            if recursive and not project_name.startswith(package):
                continue

            project = ctx.projects[project_name]

            for provider_name, provider in project.providers.items():
                line = "\t"
                if recursive:
                    line += f"{project_name}"
                    line += " " + " " * (35 - len(project_name))
                line += f"{provider_name}"
                line += " " + " " * (35 - len(provider_name))

                desc = provider.desc if provider.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                line += f"{desc}"
                output += line + "\n"
                provider_kinds = provider_kinds + 1

        if provider_kinds > 0:
            output += f"Total: {provider_kinds}\n"
        else:
            output += "\t<none>\n"
        logging.info(output)
