#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each component of an object costs: its share of the object's quote.

The quote itself is the daemon's ('supply_quote'); what is under test here is
the rule that shares it out, so the line items are written by hand and the
packages behind them are stand-ins for the two questions 'partcad.procurement'
answers.
"""

import asyncio
import types

from partcad import component_prices, procurement


def _item(name, count, *prices, currency="USD", **store):
    return {
        "name": name,
        "count": count,
        "suppliers": [
            {"name": "//:shop%d" % i, "price": price, "currency": currency} for i, price in enumerate(prices)
        ],
        **store,
    }


def test_one_of_a_line_item_is_its_cheapest_quote_shared_over_the_lot():
    units = component_prices.unit_prices(
        [
            # A box of bolts for eight of them: each costs an eighth of the box.
            _item("//:bolt", 8, 4.0, 2.0),
            _item("//:nut", 4, None, 1.0, currency="EUR"),
        ]
    )
    assert units == {
        "//:bolt": {"price": 0.25, "currency": "USD"},
        "//:nut": {"price": 0.25, "currency": "EUR"},
    }


def test_a_line_item_nobody_priced_has_no_price():
    units = component_prices.unit_prices([_item("//:bolt", 1), _item("//:nut", 1, None)])
    assert units == {}


def test_the_kinds_of_one_set_share_the_price_of_the_set():
    """Each kind was quoted the whole set; priced at a set each, two kinds would cost two sets."""
    store = {"vendor": "acme", "sku": "SET-1"}
    units = component_prices.unit_prices(
        [
            _item("//:shaft", 2, 10.0, item_in_sku="shaft", **store),
            _item("//:clip", 2, 10.0, item_in_sku="clip", **store),
        ]
    )
    # Two sets for two shafts and two clips: each shaft and each clip is half a set.
    assert units["//:shaft"]["price"] == 2.5
    assert units["//:clip"]["price"] == 2.5


class _Part:
    def __init__(self, name, procured):
        self.project_name, self.name = name.split(":")
        self.procured = procured


def _ctx(monkeypatch, parts):
    """Stand-ins for the two questions the rule asks of a package."""

    async def get_part_async(ctx, name):
        return parts.get(name)

    async def procured_as(ctx, part):
        return part.procured

    monkeypatch.setattr(procurement, "get_part_async", get_part_async)
    monkeypatch.setattr(procurement, "procured_as", procured_as)
    return types.SimpleNamespace()


def test_a_part_is_priced_as_what_it_is_procured_as(monkeypatch):
    ctx = _ctx(
        monkeypatch,
        {
            "//:bolt": _Part("//:bolt", ["//:bolt"]),
            # Cut from a sheet: it costs its piece of the quote for sheets.
            "//:blank": _Part("//:blank", ["//:sheet"]),
            # Printed from nothing anybody sells: no price, not a price of nought.
            "//:printed": _Part("//:printed", []),
            # Made from stock nobody quoted.
            "//:bracket": _Part("//:bracket", ["//:bar"]),
        },
    )
    items = [_item("//:bolt", 4, 2.0), _item("//:sheet", 2, 30.0)]

    prices = asyncio.run(component_prices.prices_async(ctx, ["//:bolt", "//:blank", "//:printed", "//:bracket"], items))

    assert prices["//:bolt"] == {"price": 0.5, "currency": "USD"}
    assert prices["//:blank"] == {"price": 15.0, "currency": "USD"}
    assert "//:printed" not in prices
    assert "//:bracket" not in prices


def test_an_assembly_sold_assembled_is_priced_as_one(monkeypatch):
    """No part name reaches it, and it is a component of what it is part of all the same."""
    ctx = _ctx(monkeypatch, {})
    prices = asyncio.run(component_prices.prices_async(ctx, [], [_item("//:gearbox", 1, 120.0)]))
    assert prices == {"//:gearbox": {"price": 120.0, "currency": "USD"}}


def test_two_currencies_are_not_added_up(monkeypatch):
    """There is no exchange rate to add them up with."""
    ctx = _ctx(monkeypatch, {"//:kit": _Part("//:kit", ["//:a", "//:b"])})
    items = [_item("//:a", 1, 1.0, currency="USD"), _item("//:b", 1, 1.0, currency="EUR")]
    assert "//:kit" not in asyncio.run(component_prices.prices_async(ctx, ["//:kit"], items))


def test_the_components_of_a_part_are_itself():
    class _Assembly:
        async def get_bom(self):
            return {"//:bolt": 4, "//:plate": 1}

    assert asyncio.run(component_prices.component_names_async(_Part("//:bolt", []))) == ["//:bolt"]
    assert asyncio.run(component_prices.component_names_async(_Assembly())) == ["//:bolt", "//:plate"]
