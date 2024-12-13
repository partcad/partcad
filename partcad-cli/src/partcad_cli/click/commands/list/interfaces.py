import rich_click as click
from partcad import logging
from partcad.logging import Process


@click.command(help="List available interfaces")
@click.option("-r", "--recursive", is_flag=True, help="Recursively process all imported packages")
@click.option(
    "-u", "--used_by", type=str, required=False, help="Only process objects used by the given assembly or scene."
)
@click.argument("package", type=str, required=False)  # help="Package to retrieve the object from"
@click.pass_obj
def cli(ctx, recursive, used_by, package):
    with Process("ListInterfaces", "this"):
        interface_count = 0
        interface_kinds = 0

        if used_by is not None:
            logging.info("Instantiating %s..." % used_by)
            ctx.get_assembly(used_by)
        else:
            ctx.get_all_packages()

        output = "PartCAD interfaces:\n"
        for project_name in ctx.projects:
            if not recursive and package is not None and package != project_name:
                continue

            if not recursive and project_name != ctx.get_current_project_path():
                continue

            if recursive and package is not None and not project_name.startswith(package):
                continue

            if recursive and package is None and not project_name.startswith(ctx.get_current_project_path()):
                continue

            project = ctx.projects[project_name]

            for interface_name, interface in project.interfaces.items():
                if used_by is not None and interface.count == 0:
                    continue

                line = "\t"
                if recursive:
                    line += "%s" % project_name
                    line += " " + " " * (35 - len(project_name))
                line += "%s" % interface_name
                if used_by is not None:
                    interface = project.get_interface(interface_name)
                    line += "(%d)" % interface.count
                    interface_count = interface_count + interface.count
                line += " " + " " * (35 - len(interface_name))

                desc = interface.desc if interface.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                line += "%s" % desc
                output += line + "\n"
                interface_kinds = interface_kinds + 1

        if interface_kinds > 0:
            if used_by is None:
                output += "Total: %d\n" % interface_kinds
            else:
                output += "Total: %d interfaces of %d kinds\n" % (
                    interface_count,
                    interface_kinds,
                )
        else:
            output += "\t<none>\n"
        logging.info(output)
