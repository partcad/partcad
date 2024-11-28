#!/usr/bin/env python3
#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-12
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc
from partcad.provider_data_cart import ProviderCart
from partcad.provider_request_quote import ProviderRequestQuote


def test_provider_quote_store_csv():
    FULL_PART_NAME = "/pub/robotics/parts/gobilda:hardware/nut_m4_0_7mm#25"
    FULL_PROVIDER_NAME = "/pub/examples/partcad/provider_store:myGarage"

    ctx = pc.init("examples/provider_store")

    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, FULL_PART_NAME))

    provider = ctx.get_provider("myGarage")
    assert provider is not None

    preferred_suppliers = asyncio.run(ctx.select_supplier(provider, cart))
    assert list(preferred_suppliers.keys())[0] == FULL_PART_NAME
    assert preferred_suppliers[FULL_PART_NAME] == FULL_PROVIDER_NAME

    supplier_carts = asyncio.run(ctx.prepare_supplier_carts(preferred_suppliers))
    quotes = asyncio.run(ctx.supplier_carts_to_quotes(supplier_carts))
    pc.logging.error("Quotes: %s" % quotes)
    assert len(quotes.keys()) == 1
    assert FULL_PROVIDER_NAME in quotes
    assert quotes[FULL_PROVIDER_NAME].result["price"] == 0.01
