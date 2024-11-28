#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from partcad.provider_data_cart import ProviderCart
import partcad as pc
import json


def cli_help_supply_find(subparsers):
    parser = subparsers.add_parser(
        "find",
        help="Find suppliers",
    )
    parser.add_argument(
        "-j",
        "--json",
        help="Produce JSON output",
        dest="json",
        action="store_true",
    )
    parser.add_argument(
        "-q",
        "--qos",
        help="Requested quality of service",
        dest="qos",
    )
    parser.add_argument(
        "--provider",
        help="Provider to use",
        dest="provider",
    )
    parser.add_argument(
        "specs",
        metavar="object[[,material],count]",
        help="Part (default) or assembly to quote, with options",
        nargs="+",
    )


def cli_supply_find(args, ctx):
    cart = ProviderCart()
    asyncio.run(cart.add_objects(ctx, args.specs))

    suppliers = {}
    if args.provider:
        provider = ctx.get_provider(args.provider)
        if not provider.is_qos_available(args.qos):
            pc.logging.error(f"Provider {provider.name} cannot provide qos: {args.qos}.")
        asyncio.run(provider.load(cart))
        for part_spec in cart.parts.values():
            suppliers[str(part_spec)] = []
            if not asyncio.run(provider.is_part_available(part_spec)):
                pc.logging.error(f"Provider {provider.name} cannot provide {part_spec.name}.")
                return
            suppliers[str(part_spec)].append(provider.name)
    else:
        suppliers = asyncio.run(ctx.find_suppliers(cart, args.qos))
        pc.logging.debug("Suppliers: %s" % str(suppliers))

    if args.json:
        print(json.dumps(suppliers))
    else:
        pc.logging.info("The requested parts are available through the following suppliers:")
        for spec_str, suppliers in suppliers.items():
            suppliers_str = ""
            for supplier in suppliers:
                suppliers_str += "\n\t\t" + str(supplier)
            pc.logging.info(f"{spec_str}:{suppliers_str}")
