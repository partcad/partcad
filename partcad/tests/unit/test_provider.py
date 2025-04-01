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


def test_provider_quote_store_csv():
    FULL_PART_NAME = "//pub/robotics/parts/gobilda:hardware/nut_m4_0_7mm#25"
    FULL_PROVIDER_NAME = "//pub/examples/partcad/provider_store:myGarage"

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


def test_provider_quote_store_csv_2():
    """Use an alias to refer to the same part."""
    PART_NAME = "//pub/examples/partcad/provider_store:nut"
    FULL_PART_NAME = "//pub/examples/partcad/provider_store:nut#1"
    FULL_PROVIDER_NAME = "//pub/examples/partcad/provider_store:myGarage"

    ctx = pc.init("examples/provider_store")

    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, PART_NAME))

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

def test_provider_user_config_params_get():
    """Load a CadQuery part using enrichment for provider and see if the parameters changed from user_config"""
    import partcad as pc
    ctx = pc.Context("examples/provider_store")
    pc.user_config.parameter_config["//pub/examples/partcad/provider_store:myGarage"] = {"currency": "INR"}
    provider = ctx.get_provider("myGarage")
    assert provider is not None
    assert provider.config["parameters"]["currency"]["default"] == "INR"
