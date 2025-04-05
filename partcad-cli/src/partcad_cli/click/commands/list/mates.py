#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext


@click.command(help="List available mating interfaces")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name  # '//' may end up having a different name

        with pc.logging.Process("ListMates", package):
            mating_kinds = 0

            if recursive:
                all_packages = ctx.get_all_packages(parent_name=package)
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            # Instantiate all interfaces in the relevant packages to get the mating data
            # finalized
            for package_name in packages:
                p = ctx.projects[package_name]
                for interface_name in p.interfaces:
                    intf = p.get_interface(interface_name)
                    intf.instantiate()

            output = "PartCAD mating interfaces:\n"
            for source_interface_name in ctx.mates:
                source_package_name = source_interface_name.split(":")[0]
                # TODO-102: @alexanderilyin: Use interface short name
                display_source_interface_name = (
                    source_interface_name if source_package_name != package else source_interface_name.split(":")[1]
                )

                for target_interface_name in ctx.mates[source_interface_name]:
                    target_package_name = target_interface_name.split(":")[0]
                    display_target_interface_name = (
                        target_interface_name if target_package_name != package else target_interface_name.split(":")[1]
                    )

                    mating = ctx.mates[source_interface_name][target_interface_name]

                    if (
                        recursive
                        and not source_package_name.startswith(package)
                        and not target_package_name.startswith(package)
                    ):
                        continue

                    if not recursive and source_package_name != package and target_package_name != package:
                        continue

                    line = "\t"
                    line += "%s" % display_source_interface_name
                    line += " " + " " * (35 - len(display_source_interface_name))
                    line += "%s" % display_target_interface_name
                    line += " " + " " * (35 - len(display_target_interface_name))

                    desc = mating.desc if mating.desc is not None else ""
                    desc = desc.replace("\n", "\n\t" + " " * 72)
                    line += "%s" % desc
                    output += line + "\n"
                    mating_kinds = mating_kinds + 1

            if mating_kinds > 0:
                output += "Total: %d mating interfaces\n" % (mating_kinds,)
            else:
                output += "\t<none>\n"
            pc.logging.info(output)
