import os
import sys

import partcad as pc
import partcad.logging as pc_logging


def cli_help_init(subparsers):
    pass
    # parser_init = subparsers.add_parser(
    #     "init",
    #     help="Initialize a new PartCAD package in this directory",
    # )
    # parser_init.add_argument(
    #     "-p",
    #     help="Initialize this package as private",
    #     dest="private",
    #     action="store_true",
    # )


def cli_init(args):
    pass
    # if not args.config_path is None:
    #     if os.path.isdir(args.config_path):
    #         dst_path = os.path.join(args.config_path, "partcad.yaml")
    #     else:
    #         dst_path = args.config_path
    # else:
    #     dst_path = "partcad.yaml"

    # if not pc.create_package(dst_path, args.private):
    #     pc_logging.error("Failed creating '%s'!" % dst_path)
