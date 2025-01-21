import rich_click as click
from partcad import logging
from partcad.logging import Process
from partcad.sentry import tracer as pc_tracer

@click.command(help="List available mating interfaces")
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
@pc_tracer.start_as_current_span("Command [pc list mates]")
def cli(ctx, recursive, used_by, package):
    package_obj = ctx.get_project(package)
    if not package_obj:
        logging.error(f"Package {package} is not found")
        return
    package = package_obj.name

    with Process("ListMates", package):
        mating_kinds = 0

        if used_by is not None:
            logging.info(f"Instantiating {used_by}...")
            ctx.get_assembly(used_by)
        else:
            ctx.get_all_packages()

        # Instantiate all interfaces in the relevant packages to get the mating data
        # finalized
        for package_name in ctx.projects:
            if not recursive and package_name != package:
                continue

            if recursive and not package_name.startswith(package):
                continue

            package = ctx.projects[package_name]
            for interface_name in package.interfaces:
                package.get_interface(interface_name)

        output = "PartCAD mating interfaces:\n"
        for source_interface_name in ctx.mates:
            source_package_name = source_interface_name.split(":")[0]
            # TODO-102: @alexanderilyin: Use interface short name
            short_source_interface_name = source_interface_name.split(":")[1]

            for target_interface_name in ctx.mates[source_interface_name]:
                target_package_name = target_interface_name.split(":")[0]
                short_target_interface_name = target_interface_name.split(":")[1]

                mating = ctx.mates[source_interface_name][target_interface_name]

                if (
                    recursive
                    and package is not None
                    and not source_package_name.startswith(package)
                    and not target_package_name.startswith(package)
                ):
                    continue

                if (
                    recursive
                    and package is None
                    and not source_package_name.startswith(ctx.get_current_project_path())
                    and not target_package_name.startswith(ctx.get_current_project_path())
                ):
                    continue

                if (
                    not recursive
                    and package is not None
                    and source_package_name != package
                    and target_package_name != package
                ):
                    continue

                if (
                    not recursive
                    and package is None
                    and source_package_name != ctx.get_current_project_path()
                    and target_package_name != ctx.get_current_project_path()
                ):
                    continue

                # source_project = ctx.projects[source_package_name]
                # target_project = ctx.projects[target_package_name]

                # source_interface = source_project.get_interface(
                #     short_source_interface_name
                # )
                # target_interface = target_project.get_interface(
                #     short_target_interface_name
                # )

                if used_by is not None and mating.count == 0:
                    continue

                line = "\t"
                line += "%s" % source_interface_name
                line += " " + " " * (35 - len(source_interface_name))
                line += "%s" % target_interface_name
                line += " " + " " * (35 - len(target_interface_name))

                desc = mating.desc if mating.desc is not None else ""
                desc = desc.replace("\n", "\n\t" + " " * 72)
                line += "%s" % desc
                output += line + "\n"
                mating_kinds = mating_kinds + 1

        if mating_kinds > 0:
            output += "Total: %d mating interfaces\n" % (mating_kinds,)
        else:
            output += "\t<none>\n"
        logging.info(output)
