import rich_click as click
from partcad import logging
from partcad.logging import Process


@click.command(help="List imported packages")
@click.pass_obj
def cli(ctx):
    with Process("List", "this"):
        # TODO: Show source (URL, PATH) of the package, probably use prettytable as well
        pkg_count = 0

        projects = ctx.get_all_packages()
        projects = sorted(projects, key=lambda p: p["name"])

        output = "PartCAD packages:\n"
        for project in projects:
            project_name = project["name"]

            line = "\t%s" % project_name
            padding_size = 60 - len(project_name)
            if padding_size < 4:
                padding_size = 4
            line += " " * padding_size
            desc = project["desc"]
            desc = desc.replace("\n", "\n" + " " * 68)
            line += "%s" % desc
            output += line + "\n"
            pkg_count = pkg_count + 1

        if pkg_count < 1:
            output += "\t<none>\n"
        logging.info(output)
