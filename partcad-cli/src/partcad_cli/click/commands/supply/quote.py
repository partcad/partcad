#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import asyncio
import copy
import json
import sys

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Get a quote from suppliers")
@click.option(
    "--json",
    "-j",
    "api",
    help="Produce JSON output",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--qos",
    "-q",
    help="Requested quality of service",
    type=str,
    show_envvar=True,
)
@click.option(
    "--provider",
    "-p",
    help="Provider to use",
    type=str,
    show_envvar=True,
)
@click.argument(
    "specs",
    metavar="object[[,material],count]",
    type=str,
    nargs=-1,
)  # help="Part (default) or assembly to quote, with options",
@click.pass_obj
def cli(cli_ctx: CliContext, api, qos, provider, specs):
    """
    TODO-117: Implementing Network Error Handling
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        with pc.logging.Process("SupplyQuote", "this"):
            cart = pc.ProviderCart(qos=qos)
            asyncio.run(cart.add_objects(ctx, specs))
            pc.logging.debug("Cart: %s" % str(cart.parts))

            if provider:
                provider_obj = ctx.get_provider(provider)
                if not provider_obj:
                    pc.logging.error(f"Provider {provider} not found.")
                    return
                preferred_suppliers = asyncio.run(ctx.select_supplier(provider_obj, cart))
                pc.logging.debug("Selected suppliers: %s" % str(preferred_suppliers))
            else:
                suppliers = asyncio.run(ctx.find_suppliers(cart))
                pc.logging.debug("Suppliers: %s" % str(suppliers))
                preferred_suppliers = ctx.select_preferred_suppliers(suppliers)
                pc.logging.debug("Preferred suppliers: %s" % str(preferred_suppliers))

            supplier_carts = asyncio.run(ctx.prepare_supplier_carts(preferred_suppliers))
            quotes = asyncio.run(ctx.supplier_carts_to_quotes(supplier_carts))
            pc.logging.debug("Quotes: %s" % str(quotes))

            if api:

                def scrub(x):
                    # Handle ProviderRequestQuote
                    if isinstance(x, pc.ProviderRequestQuote):
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
                        pc.logging.info(f"\t\t{supplier}: {cart_id}: ${price:.2f}")
                    else:
                        pc.logging.info("No provider found:")

                    for part in quote.cart.parts.values():
                        pc.logging.info(f"\t\t\t{part.name}#{part.count}")
