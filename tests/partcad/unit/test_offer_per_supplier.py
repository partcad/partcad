#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Each supplier is handed the item the way it sells it.

A part can be ordered more than one way: its own SKU, and the SKU of every
loaded alias of it that names one - another store's, another pack. A supplier
is asked about each in turn and handed the first it has, so one model is bought
from either of two stores; with '--cheapest' each way a supplier has it is
priced, and the cheapest wins, between packs and between stores.
"""

import asyncio

import pytest

import partcad as pc
from partcad import procurement
from partcad.plugin_provider_data_cart import ProviderCart, ProviderCartItem

PACKAGE = "tests/partcad/unit/data/two_stores/partcad.yaml"

# What each store asks per SKU, in dollars.
PRICES = {
    "east": {"E-B": 4.0, "E-SCREW": 0.5, "E-M": 12.0, "BOLT-1": 2.0},
    "west": {"W-B": 5.0, "W-B10": 30.0, "W-SCREW": 0.4, "W-M": 11.0, "BOLT-1": 1.5},
}


class _Store:
    """A store that sells its own vendor's SKUs, and the maker's SKUs it has a price for, and prices a cart by them."""

    def __init__(self, vendor, asked):
        self.vendor = vendor
        self.name = "//%s:store" % vendor
        self.asked = asked

    async def is_part_available(self, item):
        self.asked.append((self.vendor, item.sku))
        return item.vendor in (self.vendor, "acme") and item.sku in PRICES[self.vendor]

    def is_qos_available(self, qos):
        return True

    async def load(self, item):
        pass

    async def query_quote(self, request):
        total = 0.0
        for item in request.cart.parts.values():
            per = max(int(item.count_per_sku or 1), 1)
            total += PRICES[self.vendor][item.sku] * -(-item.count // per)
        return {"price": total, "cartId": None}


@pytest.fixture
def ctx():
    ctx = pc.Context(PACKAGE)
    asked = []
    stores = {"//east:store": _Store("east", asked), "//west:store": _Store("west", asked)}
    ctx.get_provider = lambda name, extra=None: stores.get(name)
    ctx.asked = asked
    ctx.stores = stores
    return ctx


def _item(ctx, spec):
    item = ProviderCartItem()
    asyncio.run(item.set_spec(ctx, spec))
    return item


def test_the_alternatives_are_the_parts_own_sku_then_its_aliases(ctx):
    procurement.load_suppliers(ctx, {"//east:store": {}, "//west:store": {}})
    screw = ctx._get_part("//:screw")
    assert [name for name, _ in procurement.alternatives(screw, ctx)] == ["//:screw", "//west:screw"]
    board = ctx._get_part("//:board")
    assert [name for name, _ in procurement.alternatives(board, ctx)] == [
        "//east:board",
        "//west:board",
        "//west:board-10",
    ]


def test_a_store_package_counts_once_it_is_loaded(ctx):
    board = ctx._get_part("//:board")
    assert procurement.alternatives(board, ctx) == []
    procurement.load_suppliers(ctx, {"//west:store": {}})
    assert [name for name, _ in procurement.alternatives(board, ctx)] == ["//west:board", "//west:board-10"]


def test_each_supplier_is_handed_the_sku_it_sells(ctx):
    cart = ProviderCart()
    asyncio.run(cart.add_objects(ctx, ["//:board#3", "//:screw#2"]))

    for store, expected in (
        ("//west:store", {"//:board": ("west", "W-B"), "//:screw": ("west", "W-SCREW")}),
        ("//east:store", {"//:board": ("east", "E-B"), "//:screw": ("east", "E-SCREW")}),
    ):
        chosen = asyncio.run(ctx.select_supplier(ctx.stores[store], cart))
        assert set(chosen.values()) == {store}
        carts = asyncio.run(ctx.prepare_supplier_carts(chosen, cart))
        got = {name: (item.vendor, item.sku) for name, item in carts[store].parts.items()}
        assert got == expected


def test_a_part_with_its_own_sku_is_still_sold_by_a_store_that_sells_an_alias(ctx):
    """The screw names the east store's SKU, and the west store sells it all the same."""
    item = _item(ctx, "//:screw#2")
    found = asyncio.run(ctx.find_part_suppliers(item, ProviderCart()))
    assert found == ["//east:store", "//west:store"]
    assert item.offer_by_provider == {"//east:store": "//:screw", "//west:store": "//west:screw"}


def test_without_cheapest_the_pack_that_suits_the_count_is_offered_first(ctx):
    item = _item(ctx, "//:board#7")
    asyncio.run(ctx.find_part_suppliers(item, ProviderCart()))
    # Seven come singly: a pack of ten would leave three over.
    assert item.offer_by_provider["//west:store"] == "//west:board"


def test_cheapest_prices_every_way_and_orders_the_cheapest(ctx):
    item = _item(ctx, "//:board#7")
    cart = ProviderCart(cheapest=True)
    found = asyncio.run(ctx.find_part_suppliers(item, cart))
    # West: seven singly is $35, a pack of ten $30. East: seven at $4 is $28.
    assert item.offer_by_provider["//west:store"] == "//west:board-10"
    assert item.price_by_provider == {"//east:store": 28.0, "//west:store": 30.0}
    assert found == ["//east:store", "//west:store"]
    assert ctx.select_preferred_supplier(found) == "//east:store"


def test_cheapest_compares_the_suppliers_of_a_part_with_one_way_to_order_it(ctx):
    """A maker's SKU both stores carry: no pack to choose between, but still two prices."""
    item = _item(ctx, "//:bolt#4")
    found = asyncio.run(ctx.find_part_suppliers(item, ProviderCart(cheapest=True)))
    assert item.price_by_provider == {"//east:store": 8.0, "//west:store": 6.0}
    assert found == ["//west:store", "//east:store"]


def test_cheapest_buys_the_pack_where_it_is_cheaper(ctx):
    """'Buy a pack if it is cheaper': ten singly from the west store would be $50, the pack is $30."""
    item = _item(ctx, "//:board#10")
    asyncio.run(ctx.find_part_suppliers(item, ProviderCart(cheapest=True)))
    assert item.offer_by_provider["//west:store"] == "//west:board-10"
    assert item.price_by_provider["//west:store"] == 30.0


def test_an_assembly_package_loads_the_stores_it_names(ctx, tmp_path):
    """What a package lists under 'suppliers:' is loaded before what it is made of is procured."""
    ctx.projects.pop("//east", None)
    ctx.projects.pop("//west", None)
    project = ctx.get_project("//")
    procurement.load_suppliers(ctx, asyncio.run(project.get_suppliers_async()))
    assert "//east" in ctx.projects and "//west" in ctx.projects


def test_a_part_cut_from_stock_only_the_stores_sell_can_be_made(ctx):
    """The desk's case: the stock names no SKU, and the package's suppliers publish aliases of it."""
    from partcad.qual.basic import manufacturability
    from partcad.qual.qualification import Qualification as Test

    ctx.projects.pop("//east", None)
    ctx.projects.pop("//west", None)
    check = manufacturability.ManufacturabilityTest()
    verdict = asyncio.run(check.test_part([check], ctx, ctx._get_part("//:shelf"), {}))
    assert verdict == Test.TEST_PASSED
    # The board was asked of a store as the store sells it.
    assert ("east", "E-B") in ctx.asked or ("west", "W-B") in ctx.asked


def test_a_part_cut_from_stock_nobody_sells_cannot_be_made(ctx):
    from partcad.qual.basic import manufacturability
    from partcad.qual.qualification import Qualification as Test

    ctx.projects.pop("//east", None)
    ctx.projects.pop("//west", None)
    ctx.get_project("//").suppliers = {}
    check = manufacturability.ManufacturabilityTest()
    verdict = asyncio.run(check.test_part([check], ctx, ctx._get_part("//:shelf"), {}))
    assert verdict == Test.TEST_FAILED


def test_a_part_bought_through_an_alias_needs_no_pinned_file(ctx):
    """Ordering the alias's SKU again is "the same again", as for a part that names its own SKU."""
    from partcad.qual.basic import manufacturability
    from partcad.qual.qualification import Qualification as Test

    ctx.projects.pop("//east", None)
    ctx.projects.pop("//west", None)
    check = manufacturability.ManufacturabilityTest()
    test_ctx = {}
    verdict = asyncio.run(check.test([check], ctx, ctx._get_part("//:module"), test_ctx))
    assert verdict == Test.TEST_PASSED
    # It turned on which packages are loaded, which the cache key does not say.
    assert test_ctx.get(Test.NOT_CACHEABLE)


def test_a_part_nobody_sells_needs_its_file_pinned(ctx, caplog):
    from partcad.qual.basic import manufacturability
    from partcad.qual.qualification import Qualification as Test

    ctx.projects.pop("//east", None)
    ctx.projects.pop("//west", None)
    ctx.get_project("//").suppliers = {}
    check = manufacturability.ManufacturabilityTest()
    test_ctx = {}
    part = ctx._get_part("//:module")
    with caplog.at_level("ERROR"):
        verdict = asyncio.run(check.test([check], ctx, part, test_ctx))
    assert verdict == Test.TEST_FAILED
    assert "It is not reproducible" in caplog.text
    assert test_ctx.get(Test.NOT_CACHEABLE)


def test_a_verdict_is_kept_per_set_of_suppliers_it_was_reached_with(ctx):
    """The same part asked about for two assemblies that buy from different stores is two questions."""
    from partcad.qual.basic import manufacturability

    check = manufacturability.ManufacturabilityTest()
    east = check.cache_key_context({check.SUPPLIERS: {"//east:store": None}})
    west = check.cache_key_context({check.SUPPLIERS: {"//west:store": None}})
    both = check.cache_key_context({check.SUPPLIERS: {"//east:store": None, "//west:store": None}})
    assert len({east, west, both}) == 3
    # Listed in another order, the same suppliers.
    assert both == check.cache_key_context({check.SUPPLIERS: {"//west:store": None, "//east:store": None}})
    # Nothing handed down keys as it always did.
    assert check.cache_key_context({}) == ""


def test_a_packages_suppliers_are_in_its_objects_keys(ctx):
    from partcad.qual.basic import manufacturability

    check = manufacturability.ManufacturabilityTest()
    screw = ctx._get_part("//:screw")
    with_stores = asyncio.run(check.cache_key_suffix(ctx, screw))
    ctx.get_project("//").suppliers = {"//east:store": {}}
    only_east = asyncio.run(check.cache_key_suffix(ctx, screw))
    ctx.get_project("//").suppliers = {}
    without = asyncio.run(check.cache_key_suffix(ctx, screw))
    assert len({with_stores, only_east, without}) == 3
