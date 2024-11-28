#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-11-30
#
# Licensed under Apache License, Version 2.0.
#

import partcad.logging as pc_logging
import partcad.utils as pc_utils


def cli_help_ai_regenerate(subparsers):
    parser = subparsers.add_parser(
        "regenerate",
        help="Regenerate a sketch, part or assembly",
    )

    parser.add_argument(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        dest="package",
        default=None,
    )

    group_type = parser.add_mutually_exclusive_group(required=False)
    group_type.add_argument(
        "-i",
        help="The object is an interface",
        dest="interface",
        action="store_true",
    )
    group_type.add_argument(
        "-a",
        help="The object is an assembly",
        dest="assembly",
        action="store_true",
    )
    group_type.add_argument(
        "-s",
        help="The object is a sketch",
        dest="sketch",
        action="store_true",
    )
    group_type.add_argument(
        "-S",
        help="The object is a scene",
        dest="scene",
        action="store_true",
    )

    parser.add_argument(
        "object",
        help="Path to the part (default), assembly or scene to regenerate",
        type=str,
    )


def cli_ai_regenerate(args, ctx):
    if args.sketch or args.interface or args.assembly or args.scene:
        pc_logging.error("This object type is not yet supported")
        return

    if not ":" in args.object:
        args.object = ":" + args.object
    args.package, args.object = pc_utils.resolve_resource_path(
        ctx.get_current_project_path(), args.object
    )

    package = ctx.get_project(args.package)
    obj = package.get_part(args.object)
    obj.regenerate()
