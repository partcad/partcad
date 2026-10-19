#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the parts of an assembly are looked for: its own package's suppliers too.

A package of models is usually built from a parts library somebody else
publishes, and that library may know nothing of the store the models are meant
to be bought at. So the suppliers the assembly's package names are asked about
every part it is procured from, ahead of the ones the part's own package names.

  '//:model'       - two '//lib:brick' and a '//kit:pin'; '//' buys at '//store:shop'
  '//lib'          - names no supplier at all
  '//kit'          - buys at '//store:own'
  '//other:frame'  - one '//lib:brick'; '//other' buys at '//store:own'
  '//store:priced' - a store with a 'currency' parameter, which no package names

The stores' scripts are never run: availability is replaced, and what is
checked is which providers are asked, in what order.
"""

import asyncio

import pytest

import partcad as pc
from partcad.plugin_factory_provider_store import PluginFactoryProviderStore
from partcad.plugin_provider_data_cart import ProviderCart

PACKAGE = "tests/partcad/unit/data/supply_requester/partcad.yaml"
SHOP = "//store:shop"
OWN = "//store:own"


@pytest.fixture
def asked(monkeypatch):
    """Every store has everything; returns the (provider, item) pairs asked."""
    asked = []

    async def is_part_available(self, cart_item):
        asked.append((self.name, cart_item.name))
        return True

    # The store's factory hands its own method to the provider it makes, so it
    # is replaced there rather than on 'Provider'.
    monkeypatch.setattr(PluginFactoryProviderStore, "is_part_available", is_part_available)
    return asked


def _cart(ctx, *specs):
    cart = ProviderCart()
    asyncio.run(cart.add_objects(ctx, list(specs)))
    return cart


def test_parts_carry_the_suppliers_of_the_assembly_package():
    ctx = pc.Context(PACKAGE)
    cart = _cart(ctx, "//:model")

    assert {name: list(item.suppliers) for name, item in cart.parts.items()} == {
        "//lib:brick": [SHOP],
        "//kit:pin": [SHOP],
    }
    # Procurement metadata, not something a store is told.
    assert "suppliers" not in cart.parts["//lib:brick"].compose()


def test_a_part_named_on_its_own_carries_none():
    ctx = pc.Context(PACKAGE)
    assert list(_cart(ctx, "//lib:brick").parts["//lib:brick"].suppliers) == []


def test_a_part_with_no_store_of_its_own_is_found_at_the_assembly_package_store(asked):
    ctx = pc.Context(PACKAGE)
    suppliers = asyncio.run(ctx.find_suppliers(_cart(ctx, "//:model#2")))

    assert suppliers["//lib:brick#4"] == [SHOP]


def test_the_assembly_package_store_is_asked_ahead_of_the_part_package_store(asked):
    ctx = pc.Context(PACKAGE)
    suppliers = asyncio.run(ctx.find_suppliers(_cart(ctx, "//:model")))

    assert suppliers["//kit:pin#1"] == [SHOP, OWN]
    assert ctx.select_preferred_suppliers(suppliers)["//kit:pin#1"] == SHOP


def test_a_store_named_twice_is_asked_once(asked):
    ctx = pc.Context(PACKAGE)
    cart = ProviderCart()
    item = cart.add_item(_cart(ctx, "//:model").parts["//kit:pin"])
    item.suppliers = {OWN: {}}

    assert asyncio.run(ctx.find_part_suppliers(item)) == [OWN]
    assert asked == [("own", "//kit:pin")]


def test_a_part_reached_through_two_packages_can_be_bought_where_either_says(asked):
    ctx = pc.Context(PACKAGE)
    cart = _cart(ctx, "//:model", "//other:frame")

    brick = cart.parts["//lib:brick"]
    assert brick.count == 3
    assert list(brick.suppliers) == [SHOP, OWN]


def test_without_any_supplier_nothing_is_found(asked):
    ctx = pc.Context(PACKAGE)
    suppliers = asyncio.run(ctx.find_suppliers(_cart(ctx, "//lib:brick")))

    assert not suppliers["//lib:brick#1"]
    assert asked == []


def test_a_store_that_cannot_be_loaded_is_passed_over(asked):
    # A parts library used without the package that registers its stores
    # names them all the same; the ones that are here are still asked.
    ctx = pc.Context(PACKAGE)
    cart = ProviderCart()
    item = cart.add_item(_cart(ctx, "//:model").parts["//kit:pin"])
    item.suppliers = {"//nowhere:shop": {}, "//store:closed": {}, OWN: {}}

    assert asyncio.run(ctx.find_part_suppliers(item)) == [OWN]
    assert asked == [("own", "//kit:pin")]


def test_a_part_nobody_supplies_is_kept_apart_from_the_quote(asked):
    # As 'select_supplier()' keeps a part its one provider does not have: under
    # '', so that the parts that are supplied are still quoted.
    ctx = pc.Context(PACKAGE)
    suppliers = asyncio.run(ctx.find_suppliers(_cart(ctx, "//lib:brick", "//kit:pin")))
    preferred = ctx.select_preferred_suppliers(suppliers)

    assert preferred == {"//lib:brick#1": "", "//kit:pin#1": OWN}
    carts = asyncio.run(ctx.prepare_supplier_carts(preferred))
    assert {name: list(cart.parts) for name, cart in carts.items()} == {"": ["//lib:brick"], OWN: ["//kit:pin"]}


def test_a_store_named_with_parameters_is_quoted_as_that_store(asked):
    # 'suppliers: {//store:priced: {currency: EUR}}' is an instance of its own,
    # and what is returned is its name, so that the carts and quotes made from
    # it reach the instance that was asked rather than one with the defaults.
    ctx = pc.Context(PACKAGE)
    cart = ProviderCart()
    item = cart.add_item(_cart(ctx, "//:model").parts["//kit:pin"])
    item.suppliers = {"//store:priced": {"currency": "EUR"}}

    found = asyncio.run(ctx.find_part_suppliers(item))

    assert found[0] == "//store:priced;currency=EUR"
    assert ctx.get_provider(found[0]) is ctx.get_provider("//store:priced", {"currency": "EUR"})
    assert ctx.get_provider(found[0]) is not ctx.get_provider("//store:priced")
