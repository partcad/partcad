#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-23
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from pprint import pformat

import partcad.logging as pc_logging


def cli_help_info(subparsers):
    parser_info = subparsers.add_parser(
        "info",
        help="Show detailed info on a part, assembly or scene",
    )

    parser_info.add_argument(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        dest="package",
        default=None,
    )

    group_type = parser_info.add_mutually_exclusive_group(required=False)
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

    parser_info.add_argument(
        "object",
        help="Part (default), assembly or scene to show",
        type=str,
    )

    parser_info.add_argument(
        "-p",
        "--param",
        metavar="<param_name>=<param_value>",
        help="Assign a value to the parameter",
        dest="params",
        action="append",
    )


def cli_info(args, ctx):
    params = {}
    if not args.params is None:
        for kv in args.params:
            k, v = kv.split("=")
            params[k] = v

    if args.package is None:
        if ":" in args.object:
            path = args.object
        else:
            path = ":" + args.object
    else:
        path = args.package + ":" + args.object

    if args.assembly:
        obj = ctx.get_assembly(path, params=params)
    elif args.interface:
        obj = ctx.get_interface(path)
    elif args.sketch:
        obj = ctx.get_sketch(path, params=params)
    else:
        obj = ctx.get_part(path, params=params)

    if obj is None:
        if args.package is None:
            pc_logging.error("Object %s not found" % args.object)
        else:
            pc_logging.error("Object %s not found in package %s" % (args.object, args.package))
    else:
        pc_logging.info("CONFIGURATION: %s" % pformat(obj.config))
        info = obj.info()
        for k, v in info.items():
            pc_logging.info("INFO: %s: %s" % (k, pformat(v)))
