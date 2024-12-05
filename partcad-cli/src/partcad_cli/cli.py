#!/usr/bin/env python
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#

import argparse
import logging
import sys
import partcad as pc
from .cli_add import *
from .cli_list import *
from .cli_inspect import *
from .cli_supply_find import *
from .cli_supply_caps import *
from .cli_supply_order import *
from .cli_supply_quote import *
from .cli_test import *


# Initialize plugins that are not enabled by default
pc.plugins.export_png = pc.PluginExportPngReportlab()


def main():
    parser = argparse.ArgumentParser(
        description="PartCAD command line tool",
    )
    parser.add_argument(
        "-v",
        help="Increase the level of verbosity",
        dest="verbosity",
        action="count",
        default=0,
    )
    parser.add_argument(
        "-q",
        help="Decrease the level of verbosity",
        dest="quiet",
        action="count",
        default=0,
    )
    parser.add_argument(
        "--no-ansi",
        help="Plain logging output. Do not use colors or animations.",
        dest="no_ansi",
        action="store_true",
    )
    parser.add_argument(
        "-p",
        help="Package path (a YAML file or a directory with 'partcad.yaml')",
        type=str,
        default=None,
        dest="config_path",
    )
    # TODO(clairbee): add a config option to change logging mechanism and level

    # Top level commands
    subparsers = parser.add_subparsers(dest="command")
    cli_help_add(subparsers)
    cli_help_list(subparsers)
    cli_help_inspect(subparsers)
    cli_help_test(subparsers)

    # AI subcommands
    parser_ai = subparsers.add_parser(
        "ai",
        help="AI related commands",
    )
    ai_subparsers = parser_ai.add_subparsers(
        dest="ai_command",
        required=True,
    )

    # Supply subcommands
    parser_supply = subparsers.add_parser(
        "supply",
        help="Supplier related commands",
    )
    supply_subparsers = parser_supply.add_subparsers(
        dest="supply_command",
        required=True,
    )
    cli_help_supply_find(supply_subparsers)
    cli_help_supply_caps(supply_subparsers)
    cli_help_supply_quote(supply_subparsers)
    cli_help_supply_order(supply_subparsers)

    args = parser.parse_args()

    # Configure logging
    if not args.no_ansi:
        pc.logging_ansi_terminal_init()
    else:
        logging.getLogger("partcad").propagate = True
        logging.basicConfig()
        # logging.getLogger("partcad").info("test")
        # logging.getLogger("partcad").propagate = True

    if args.quiet > 0:
        pc.logging.setLevel(logging.CRITICAL + 1)
    else:
        if args.verbosity > 0:
            pc.logging.setLevel(logging.DEBUG)
        else:
            pc.logging.setLevel(logging.INFO)

    try:
        # Initialize the context
        if not args.config_path is None:
            ctx = pc.init(args.config_path)
        else:
            ctx = pc.init()

        # Handle the command
        if args.command == "add":
            with pc.logging.Process("Add", "this"):
                cli_add(args, ctx)

        elif args.command == "add-part":
            with pc.logging.Process("AddPart", "this"):
                cli_add_part(args, ctx)

        elif args.command == "add-assembly":
            with pc.logging.Process("AddAssy", "this"):
                cli_add_assembly(args, ctx)

        elif args.command == "list-all":
            with pc.logging.Process("ListAll", "this"):
                cli_list_sketches(args, ctx)

        elif args.command == "list-sketches":
            with pc.logging.Process("ListSketches", "this"):
                cli_list_sketches(args, ctx)

        elif args.command == "inspect":
            with pc.logging.Process("inspect", "this"):
                cli_inspect(args, ctx)

        elif args.command == "supply":
            if args.supply_command == "find":
                with pc.logging.Process("SupplyFind", "this"):
                    cli_supply_find(args, ctx)
            elif args.supply_command == "caps":
                with pc.logging.Process("SupplyCaps", "this"):
                    cli_supply_caps(args, ctx)
            elif args.supply_command == "quote":
                with pc.logging.Process("SupplyQuote", "this"):
                    cli_supply_quote(args, ctx)
            elif args.supply_command == "order":
                with pc.logging.Process("SupplyOrder", "this"):
                    cli_supply_order(args, ctx)
            else:
                print("Unknown supply command.\n")
                parser.print_help()

        elif args.command == "test":
            with pc.logging.Process("Test", "this"):
                cli_test(args, ctx)

        else:
            print("Unknown command.\n")
            parser.print_help()
    except:
        pc.logging.exception("PartCAD CLI exception")

    if not args.no_ansi:
        pc.logging_ansi_terminal_fini()


if __name__ == "__main__":
    main()
