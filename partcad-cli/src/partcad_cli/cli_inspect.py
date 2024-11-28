#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import partcad.logging as pc_logging


# TODO(clairbee): fix type checking here
# def cli_help_inspect(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]):
def cli_help_inspect(subparsers):
    parser_inspect = subparsers.add_parser(
        "inspect",
        help="Visualize a part, assembly or scene",
    )

    parser_inspect.add_argument(
        "-V",
        help="Produce a verbal output instead of a visual one",
        dest="verbal",
        action="store_true",
    )

    parser_inspect.add_argument(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        dest="package",
        default=None,
    )

    group_type = parser_inspect.add_mutually_exclusive_group(required=False)
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

    parser_inspect.add_argument(
        "object",
        help="Path to the part (default), assembly or scene to inspect",
        type=str,
    )

    parser_inspect.add_argument(
        "-p",
        "--param",
        metavar="<param_name>=<param_value>",
        help="Assign a value to the parameter",
        dest="params",
        action="append",
    )


def cli_inspect(args, ctx):
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
        if args.verbal:
            if args.package is None:
                package_obj = ctx.get_project("/")
            else:
                package_obj = ctx.get_project(args.package)

            summary = obj.get_summary(package_obj)
            pc_logging.info("Summary: %s" % summary)
            if args.quiet > 0:
                print("%s" % summary)
        else:
            obj.show()
