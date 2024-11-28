#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#


def cli_help_supply_order(subparsers):
    parser = subparsers.add_parser(
        "order",
        help="Order from suppliers",
    )


def cli_supply_order(args, ctx):
    pass
