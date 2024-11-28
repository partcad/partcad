#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import time

import partcad as pc


def cli_help_list(subparsers):
    parser_list = subparsers.add_parser(
        "list",
        help="List imported packages",
    )
    parser_list_all = subparsers.add_parser(
        "list-all",
        help="List available parts, assemblies and scenes",
    )
    parser_list_sketches = subparsers.add_parser(
        "list-sketches",
        help="List available sketches",
    )
    parser_list_interfaces = subparsers.add_parser(
        "list-interfaces",
        help="List available interfaces",
    )
    parser_list_mates = subparsers.add_parser(
        "list-mates",
        help="List available mating interfaces",
    )
    parser_list_parts = subparsers.add_parser(
        "list-parts",
        help="List available parts",
    )
    parser_list_assemblies = subparsers.add_parser(
        "list-assemblies",
        help="List available assemblies",
    )

    parser_list_all.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )
    parser_list_sketches.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )
    parser_list_interfaces.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )
    parser_list_mates.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )
    parser_list_parts.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )
    parser_list_assemblies.add_argument(
        "-r",
        help="Recursively process all imported packages",
        dest="recursive",
        action="store_true",
    )

    parser_list_all.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )
    parser_list_sketches.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )
    parser_list_interfaces.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )
    parser_list_mates.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )
    parser_list_parts.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )
    parser_list_assemblies.add_argument(
        "-u",
        help="Only process objects used by the given assembly or scene.",
        dest="used_by",
        type=str,
        required=False,
    )

    parser_list_all.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )
    parser_list_sketches.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )
    parser_list_interfaces.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )
    parser_list_mates.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )
    parser_list_parts.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )
    parser_list_assemblies.add_argument(
        "package",
        help="Package to retrieve the object from",
        type=str,
        nargs="?",
    )


def cli_list(args, ctx):
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
    pc.logging.info(output)


def cli_list_sketches(args, ctx):
    sketch_count = 0
    sketch_kinds = 0

    if args.used_by is not None:
        pc.logging.info("Instantiating %s..." % args.used_by)
        ctx.get_assembly(args.used_by)
    else:
        ctx.get_all_packages()

    output = "PartCAD sketches:\n"
    for project_name in ctx.projects:
        if (
            not args.recursive
            and args.package is not None
            and args.package != project_name
        ):
            continue

        if (
            not args.recursive
            and project_name != ctx.get_current_project_path()
        ):
            continue

        if (
            args.recursive
            and hasattr(args, "package")
            and args.package is not None
            and not project_name.startswith(args.package)
        ):
            continue

        if (
            args.recursive
            and (not hasattr(args, "package") or args.package is None)
            and not project_name.startswith(ctx.get_current_project_path())
        ):
            continue

        project = ctx.projects[project_name]

        for sketch_name, sketch in project.sketches.items():
            if args.used_by is not None and sketch.count == 0:
                continue

            line = "\t"
            if args.recursive:
                line += "%s" % project_name
                line += " " + " " * (35 - len(project_name))
            line += "%s" % sketch_name
            if args.used_by is not None:
                sketch = project.sketches[sketch_name]
                line += "(%d)" % sketch.count
                sketch_count = sketch_count + sketch.count
            line += " " + " " * (35 - len(sketch_name))

            desc = sketch.desc if sketch.desc is not None else ""
            desc = desc.replace(
                "\n", "\n" + " " * (80 if args.recursive else 44)
            )
            line += "%s" % desc
            output += line + "\n"
            sketch_kinds = sketch_kinds + 1

    if sketch_kinds > 0:
        if args.used_by is None:
            output += "Total: %d\n" % sketch_kinds
        else:
            output += "Total: %d sketches of %d kinds\n" % (
                sketch_count,
                sketch_kinds,
            )
    else:
        output += "\t<none>\n"
    pc.logging.info(output)


def cli_list_interfaces(args, ctx):
    interface_count = 0
    interface_kinds = 0

    if args.used_by is not None:
        pc.logging.info("Instantiating %s..." % args.used_by)
        ctx.get_assembly(args.used_by)
    else:
        ctx.get_all_packages()

    output = "PartCAD interfaces:\n"
    for project_name in ctx.projects:
        if (
            not args.recursive
            and args.package is not None
            and args.package != project_name
        ):
            continue

        if (
            not args.recursive
            and project_name != ctx.get_current_project_path()
        ):
            continue

        if (
            args.recursive
            and hasattr(args, "package")
            and args.package is not None
            and not project_name.startswith(args.package)
        ):
            continue

        if (
            args.recursive
            and (not hasattr(args, "package") or args.package is None)
            and not project_name.startswith(ctx.get_current_project_path())
        ):
            continue

        project = ctx.projects[project_name]

        for interface_name, interface in project.interfaces.items():
            if args.used_by is not None and interface.count == 0:
                continue

            line = "\t"
            if args.recursive:
                line += "%s" % project_name
                line += " " + " " * (35 - len(project_name))
            line += "%s" % interface_name
            if args.used_by is not None:
                interface = project.get_interface(interface_name)
                line += "(%d)" % interface.count
                interface_count = interface_count + interface.count
            line += " " + " " * (35 - len(interface_name))

            desc = interface.desc if interface.desc is not None else ""
            desc = desc.replace(
                "\n", "\n" + " " * (80 if args.recursive else 44)
            )
            line += "%s" % desc
            output += line + "\n"
            interface_kinds = interface_kinds + 1

    if interface_kinds > 0:
        if args.used_by is None:
            output += "Total: %d\n" % interface_kinds
        else:
            output += "Total: %d interfaces of %d kinds\n" % (
                interface_count,
                interface_kinds,
            )
    else:
        output += "\t<none>\n"
    pc.logging.info(output)


def cli_list_mates(args, ctx):
    mating_kinds = 0

    if args.used_by is not None:
        pc.logging.info("Instantiating %s..." % args.used_by)
        ctx.get_assembly(args.used_by)
    else:
        ctx.get_all_packages()

    # Instantiate all interfaces in the relevant packages to get the mating data
    # finalized
    for package_name in ctx.projects:
        if not args.recursive:
            if (
                hasattr(args, "package")
                and args.package is not None
                and package_name != args.package
            ):
                continue
            if (
                not hasattr(args, "package") or args.package is None
            ) and package_name != ctx.get_current_project_path():
                continue

        if args.recursive:
            if (
                hasattr(args, "package")
                and args.package is not None
                and not package_name.startswith(args.package)
            ):
                continue
            if (
                not hasattr(args, "package") or args.package is None
            ) and not package_name.startswith(ctx.get_current_project_path()):
                continue

        package = ctx.projects[package_name]
        for interface_name in package.interfaces:
            package.get_interface(interface_name)

    output = "PartCAD mating interfaces:\n"
    for source_interface_name in ctx.mates:
        source_package_name = source_interface_name.split(":")[0]
        short_source_interface_name = source_interface_name.split(":")[1]

        for target_interface_name in ctx.mates[source_interface_name]:
            target_package_name = target_interface_name.split(":")[0]
            short_target_interface_name = target_interface_name.split(":")[1]

            mating = ctx.mates[source_interface_name][target_interface_name]

            if (
                args.recursive
                and hasattr(args, "package")
                and args.package is not None
                and not source_package_name.startswith(args.package)
                and not target_package_name.startswith(args.package)
            ):
                continue

            if (
                args.recursive
                and (not hasattr(args, "package") or args.package is None)
                and not source_package_name.startswith(
                    ctx.get_current_project_path()
                )
                and not target_package_name.startswith(
                    ctx.get_current_project_path()
                )
            ):
                continue

            if (
                not args.recursive
                and hasattr(args, "package")
                and args.package is not None
                and source_package_name != args.package
                and target_package_name != args.package
            ):
                continue

            if (
                not args.recursive
                and (not hasattr(args, "package") or args.package is None)
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

            if args.used_by is not None and mating.count == 0:
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
    pc.logging.info(output)


def cli_list_parts(args, ctx):
    part_count = 0
    part_kinds = 0

    if args.used_by is not None:
        pc.logging.info("Instantiating %s..." % args.used_by)
        ctx.get_assembly(args.used_by)
    else:
        ctx.get_all_packages()

    output = "PartCAD parts:\n"
    for project_name in ctx.projects:
        if (
            not args.recursive
            and args.package is not None
            and args.package != project_name
        ):
            continue

        if (
            not args.recursive
            and project_name != ctx.get_current_project_path()
        ):
            continue

        if (
            args.recursive
            and hasattr(args, "package")
            and args.package is not None
            and not project_name.startswith(args.package)
        ):
            continue

        if (
            args.recursive
            and (not hasattr(args, "package") or args.package is None)
            and not project_name.startswith(ctx.get_current_project_path())
        ):
            continue

        project = ctx.projects[project_name]

        for part_name, part in project.parts.items():
            if args.used_by is not None and part.count == 0:
                continue

            line = "\t"
            if args.recursive:
                line += "%s" % project_name
                line += " " + " " * (35 - len(project_name))
            line += "%s" % part_name
            if args.used_by is not None:
                part = project.parts[part_name]
                line += "(%d)" % part.count
                part_count = part_count + part.count
            line += " " + " " * (35 - len(part_name))

            desc = part.desc if part.desc is not None else ""
            desc = desc.replace(
                "\n", "\n" + " " * (84 if args.recursive else 44)
            )
            line += "%s" % desc
            output += line + "\n"
            part_kinds = part_kinds + 1

    if part_kinds > 0:
        if args.used_by is None:
            output += "Total: %d\n" % part_kinds
        else:
            output += "Total: %d parts of %d kinds\n" % (part_count, part_kinds)
    else:
        output += "\t<none>\n"
    pc.logging.info(output)


def cli_list_assemblies(args, ctx):
    assy_count = 0
    assy_kinds = 0

    if args.used_by is not None:
        pc.logging.info("Instantiating %s..." % args.used_by)
        # TODO(clairbee): do not call it twice in 'list-all'
        ctx.get_assembly(args.used_by)
    else:
        ctx.get_all_packages()

    output = "PartCAD assemblies:\n"
    for project_name in ctx.projects:
        if (
            not args.recursive
            and args.package is not None
            and args.package != project_name
        ):
            continue

        if (
            not args.recursive
            and project_name != ctx.get_current_project_path()
        ):
            continue

        if (
            args.recursive
            and hasattr(args, "package")
            and args.package is not None
            and not project_name.startswith(args.package)
        ):
            continue

        if (
            args.recursive
            and (not hasattr(args, "package") or args.package is None)
            and not project_name.startswith(ctx.get_current_project_path())
        ):
            continue

        project = ctx.projects[project_name]

        for assy_name, assy in project.assemblies.items():
            if args.used_by is not None and assy.count == 0:
                continue

            line = "\t"
            if args.recursive:
                line += "%s" % project_name
                line += " " + " " * (35 - len(project_name))
            line += "%s" % assy_name
            if args.used_by is not None:
                assy = project.assemblies[assy_name]
                line += "(%d)" % assy.count
                assy_count = assy_count + assy.count
            line += " " + " " * (35 - len(assy_name))

            desc = assy.desc if assy.desc is not None else ""
            desc = desc.replace(
                "\n", "\n" + " " * (84 if args.recursive else 44)
            )
            line += "%s" % desc
            output += line + "\n"
            assy_kinds = assy_kinds + 1

    if assy_kinds > 0:
        if args.used_by is None:
            output += "Total: %d\n" % assy_kinds
        else:
            output += "Total: %d assemblies of %d kinds\n" % (
                assy_count,
                assy_kinds,
            )
    else:
        output += "\t<none>\n"
    pc.logging.info(output)
