#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A part that says nothing of how to buy it is bought through an alias of it that does.

One piece of geometry is sold under several SKUs - a resistor on cut tape and on
a reel, screws in bags of 25 and of 100 - and each is written as an alias of the
part with a vendor, an SKU and a pack size of its own. The part is then bought:
in Build vs Buy, in the bills of materials and in the cart, which orders it by
whichever of those aliases suits the number it needs. Only aliases that are
loaded count: nothing is fetched to find one.
"""

import asyncio

import pytest

import partcad as pc
from partcad import build_plan, procurement
from partcad.plugin_provider_data_cart import ProviderCart, ProviderCartItem

PACKAGE = "tests/partcad/unit/data/bought_through_alias/partcad.yaml"


@pytest.fixture
def ctx():
    return pc.Context(PACKAGE)


def _part(ctx, name):
    return ctx._get_part("//:" + name)


def _offered(ctx, part):
    return [(name, record.vendor, record.sku, record.count_per_sku) for name, record in procurement.offers(part, ctx)]


def test_a_part_with_aliases_that_name_skus_is_bought(ctx):
    resistor = _part(ctx, "resistor")
    assert not resistor.get_store_data().is_purchasable
    assert procurement.is_bought(resistor, ctx)
    assert _offered(ctx, resistor) == [
        ("//:resistor-cut-tape", "digikey", "R-CT", 1),
        ("//:resistor-reel", "digikey", "R-TR", 5000),
    ]
    # Procured as itself: the alias is what it is ordered by, not what it is.
    assert asyncio.run(procurement.procured_as(ctx, resistor)) == ["//:resistor"]


@pytest.mark.parametrize(
    "name, count, chosen",
    [
        ("resistor", 1, "//:resistor-cut-tape"),
        ("resistor", 10, "//:resistor-cut-tape"),
        ("resistor", 5000, "//:resistor-reel"),
        ("resistor", 10000, "//:resistor-reel"),
        ("screw", 120, "//:screw-25"),
        ("screw", 100, "//:screw-100"),
        ("screw", 200, "//:screw-100"),
        ("screw", 30, "//:screw-25"),
    ],
)
def test_the_pack_is_chosen_by_how_many_are_needed(ctx, name, count, chosen):
    assert procurement.choose(procurement.offers(_part(ctx, name), ctx), count)[0] == chosen


def test_an_alias_of_an_alias_is_followed(ctx):
    assert _offered(ctx, _part(ctx, "nut")) == [("//:m3-nut-bag", "acme", "N-50", 50)]
    # And the alias in the middle, which says nothing either, is bought the same way.
    assert _offered(ctx, _part(ctx, "m3-nut")) == [("//:m3-nut-bag", "acme", "N-50", 50)]


def test_a_part_that_says_for_itself_is_bought_as_it_says(ctx):
    assert _offered(ctx, _part(ctx, "plate")) == [("//:plate", "acme", "PLATE-1", 1)]


def test_an_alias_that_names_no_sku_buys_nothing(ctx):
    assert not procurement.is_bought(_part(ctx, "bracket"), ctx)
    assert not procurement.is_bought(_part(ctx, "bracket-named"), ctx)


def test_only_loaded_aliases_count(ctx):
    washer = _part(ctx, "washer")
    assert not procurement.is_bought(washer, ctx)
    # Nor without a context, which is where the aliases are found.
    assert not procurement.is_bought(_part(ctx, "resistor"))
    assert ctx.get_project("//catalog") is not None
    assert _offered(ctx, washer) == [("//catalog:washer-bag", "acme", "W-100", 100)]


def test_the_cart_orders_by_the_alias_that_suits_the_count(ctx):
    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, "//:resistor#10"))
    item = cart.parts["//:resistor"]
    assert (item.vendor, item.sku, item.count_per_sku, item.via) == ("digikey", "R-CT", 1, "//:resistor-cut-tape")

    asyncio.run(cart.add_object(ctx, "//:resistor#4990"))
    item = cart.parts["//:resistor"]
    assert item.count == 5000
    assert (item.vendor, item.sku, item.count_per_sku, item.via) == ("digikey", "R-TR", 5000, "//:resistor-reel")
    composed = cart.compose()
    assert composed["skus"] == [{"vendor": "digikey", "sku": "R-TR", "count": 1, "parts": ["//:resistor"]}]
    assert composed["parts"]["//:resistor"]["sku"] == "R-TR"


def test_a_cart_item_on_its_own_is_ordered_by_its_own_count(ctx):
    item = ProviderCartItem()
    asyncio.run(item.set_spec(ctx, "//:screw#120"))
    assert (item.sku, item.count_per_sku) == ("S-25", 25)


def test_suppliers_of_the_alias_package_are_asked(ctx):
    catalog = ctx.get_project("//catalog")
    catalog.suppliers = {"store": {}}
    asked = []

    def get_provider(name, extra=None):
        asked.append(name)
        return None

    item = ProviderCartItem()
    asyncio.run(item.set_spec(ctx, "//:washer#3"))
    assert item.via == "//catalog:washer-bag"
    ctx.get_provider = get_provider
    asyncio.run(ctx.find_part_suppliers(item))
    assert asked == ["//catalog:store"]


def test_build_vs_buy_offers_to_buy_it(ctx):
    tree, _index = asyncio.run(build_plan.tree_async(ctx, _part(ctx, "screw")))
    assert tree["buy"] is True
    assert (tree["vendor"], tree["sku"]) == ("acme", "S-25")
    assert [offer["name"] for offer in tree["offers"]] == ["//:screw-25", "//:screw-100"]

    tree, _index = asyncio.run(build_plan.tree_async(ctx, _part(ctx, "bracket")))
    assert tree["buy"] is False
    assert "offers" not in tree


def test_a_part_bought_through_an_alias_is_not_asked_what_it_is_made_of(ctx, caplog):
    """A store's SKU is what it is: no "has no 'material'" for it, as for a part that names its own SKU."""
    with caplog.at_level("WARNING"):
        item = ProviderCartItem()
        asyncio.run(item.set_spec(ctx, "//:resistor#10"))
    assert item.sku == "R-CT"
    assert "has no" not in caplog.text
