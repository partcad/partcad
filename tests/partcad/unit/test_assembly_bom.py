#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The detailed bill of materials an assembly reports.

The fixture package ('data/assembly_bom_store') is a top level assembly built out
of two sub-assemblies and a loose part. Both sub-assemblies declare a vendor and
an SKU, so both are ordered whole: what is listed is what has to be procured,
and a sub-assembly that says what to order it by is that. Only one of them is in
the store's stock, and that makes no difference here - whether anybody has one
today is the supply quote's question, not the bill of materials'.
"""

import asyncio

import pytest

import partcad as pc

DATA = "tests/partcad/unit/data/assembly_bom_store"

CUBE = "//sub:cube"
UNIT = "//sub:unit"
PANEL = "//sub:panel"


def _bom(stop_at_purchasable=False, with_context=True):
    ctx = pc.Context(DATA)
    top = ctx._get_assembly(":top")
    assert top is not None
    return asyncio.run(
        top.get_bom_detailed_async(ctx if with_context else None, stop_at_purchasable=stop_at_purchasable)
    )


def _counts(bom):
    return {name: (entry["kind"], entry["count"]) for name, entry in bom.items()}


def test_a_sub_assembly_with_a_vendor_and_an_sku_is_ordered_whole():
    """Two units and a panel, each a line item of its own; the cubes inside them are not listed."""
    assert _counts(_bom()) == {UNIT: ("assembly", 2), PANEL: ("assembly", 1), CUBE: ("part", 1)}


def test_whether_it_is_in_stock_makes_no_difference():
    """The panel is out of stock and still a line item: the declaration decides, offline."""
    assert _bom()[PANEL]["sku"] == "PANEL-1"
    assert _counts(_bom(with_context=False)) == _counts(_bom())


def test_stop_at_purchasable_is_accepted_and_changes_nothing():
    assert _counts(_bom(stop_at_purchasable=True)) == _counts(_bom())


def test_bom_detailed_carries_the_store_data():
    """A line item says what to order, not only how many are needed."""
    bom = _bom()

    assert bom[UNIT]["vendor"] == "partcad"
    assert bom[UNIT]["sku"] == "UNIT-1"
    assert bom[UNIT]["count_per_sku"] == 1
    # The cube is not sold on its own, so it carries no store data.
    assert bom[CUBE]["vendor"] is None
    assert bom[CUBE]["sku"] is None
    assert bom[CUBE]["desc"] == "A cube"


@pytest.mark.parametrize("with_context", [True, False])
def test_bom_detailed_counts_what_the_supply_bom_counts(with_context):
    """The bill of materials and the cart are one rule, so they agree on every count."""
    ctx = pc.Context(DATA)
    top = ctx._get_assembly(":top")
    supply = asyncio.run(top.get_supply_bom(ctx if with_context else None))
    detailed = asyncio.run(top.get_bom_detailed_async(ctx if with_context else None))

    assert {name: entry["count"] for name, entry in detailed.items()} == supply
