import rich_click as click

import asyncio
import copy
from partcad.provider_data_cart import *
from partcad.provider_request_quote import *
import partcad as pc
import json
import sys


@click.command(help="Get a quote from suppliers")
@click.option("--json", "-j", "api", help="Produce JSON output", is_flag=True)
@click.option("--qos", "-q", help="Requested quality of service", type=str)
@click.option("--provider", "-p", help="Provider to use", type=str)
@click.option(
    "--specs",
    "-s",
    metavar="object[[,material],count]",
    type=str,
    multiple=True,
    help="Part (default) or assembly to quote, with options",
)
@click.pass_obj
def cli(ctx, api, qos, provider, specs):
    """
    TODO-117: Implementing Network Error Handling
    """

    with pc.logging.Process("SupplyQuote", "this"):
        cart = ProviderCart(qos=qos)
        asyncio.run(cart.add_objects(ctx, specs))
        pc.logging.debug("Cart: %s" % str(cart.parts))

        if provider:
            provider = ctx.get_provider(provider)
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

        if api:

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
                    pc.logging.info(f"\t\t{supplier}: {cart_id}: ${price:.2f}")
                else:
                    pc.logging.info("No provider found:")

                for part in quote.cart.parts.values():
                    pc.logging.info(f"\t\t\t{part.name}#{part.count}")
