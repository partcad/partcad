#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import copy
from partcad.provider_data_cart import *
from partcad.provider_request_quote import *
from partcad.utils import resolve_resource_path
import partcad as pc
import json
import sys


def cli_help_supply_quote(subparsers):
    parser = subparsers.add_parser(
        "quote",
        help="Get a quote from suppliers",
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


def cli_supply_quote(args, ctx):
    cart = ProviderCart(qos=args.qos)
    asyncio.run(cart.add_objects(ctx, args.specs))
    pc.logging.debug("Cart: %s" % str(cart.parts))

    if args.provider:
        provider = ctx.get_provider(args.provider)
        preferred_suppliers = asyncio.run(ctx.select_supplier(provider, cart))
        pc.logging.debug("Selected suppliers: %s" % str(preferred_suppliers))
    else:
        suppliers = asyncio.run(ctx.find_suppliers(cart))
        pc.logging.debug("Suppliers: %s" % str(suppliers))
        preferred_suppliers = ctx.select_preferred_suppliers(suppliers)
        pc.logging.debug("Preferred suppliers: %s" % str(preferred_suppliers))

    supplier_carts = asyncio.run(ctx.prepare_supplier_carts(preferred_suppliers))
    quotes = asyncio.run(ctx.supplier_carts_to_quotes(supplier_carts))
    pc.logging.debug("Quotes: %s" % str(quotes))

    if args.json:

        def scrub(x):
            # Handle ProviderRequestQuote
            if isinstance(x, ProviderRequestQuote):
                x = x.compose()

            ret = copy.deepcopy(x)
            # Handle dictionaries. Scrub all values
            if isinstance(x, dict):
                for k, v in copy.copy(list(ret.items())):
                    if k == "binary":
                        del ret[k]
                    else:
                        ret[k] = scrub(v)
            elif isinstance(x, list):
                # Handle lists. Scrub all values
                for i, v in enumerate(ret):
                    ret[i] = scrub(v)

            # Finished scrubbing
            return ret

        ret = json.dumps(scrub(quotes), indent=4)
        sys.stdout.write(ret + "\n")
        sys.stdout.flush()
    else:
        pc.logging.info("The following quotes are received:")
        for supplier in sorted(quotes.keys(), reverse=True):
            quote = quotes[supplier]
            if supplier:
                if not quote.result:
                    pc.logging.info(f"\t\t{supplier}: No quote received")
                    continue
                price = quote.result["price"]
                cart_id = quote.result["cartId"]
                pc.logging.info(
                    "\t\t%s: %s: $%0.2f"
                    % (
                        supplier,
                        cart_id,
                        price,
                    )
                )
            else:
                pc.logging.info(f"\t\tNo provider found:")

            for part in quote.cart.parts.values():
                pc.logging.info(f"\t\t\t{part.name}#{part.count}")
