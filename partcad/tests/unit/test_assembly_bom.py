#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The detailed bill of materials an assembly reports.

The fixture package ('data/assembly_bom_store') is a top level assembly built out
of two sub-assemblies and a loose part. Both sub-assemblies declare a vendor and
an SKU, so both look purchasable; only one of them is in the store's stock, which
is what tells the two halves of the purchasability rule apart.
"""

import asyncio

import pytest

import partcad as pc

DATA = "partcad/tests/unit/data/assembly_bom_store"

CUBE = "//sub:cube"
UNIT = "//sub:unit"
PANEL = "//sub:panel"

# What 'sub/stock.csv' has: the unit, and nothing else.
IN_STOCK = {("partcad", "UNIT-1")}


@pytest.fixture
def store(monkeypatch):
    """Answer the store's availability queries without the Python sandbox.

    What the assembly's store data turns into, and how the answer is read back,
    is the path these tests are about; running 'sub/myStore.py' in a sandbox is
    not, and features/bom.feature covers that end to end. The request is checked
    here rather than merely answered: a provider that is asked about the wrong
    item would otherwise still report it as available.
    """
    from partcad.plugin_factory_python import PluginFactoryPython

    async def query_script(self, plugin, script_name, request):
        assert script_name == "avail"
        # An availability request names the item by its store data alone, so
        # this is also where a cart item built from an assembly is checked.
        assert (request["vendor"], request["sku"]) in IN_STOCK | {("partcad", "PANEL-1")}
        assert request["count"] == 1 and request["count_per_sku"] == 1
        return {"available": (request["vendor"], request["sku"]) in IN_STOCK}

    monkeypatch.setattr(PluginFactoryPython, "query_script", query_script)


def _bom(stop_at_purchasable=False, with_context=True):
    ctx = pc.Context(DATA)
    top = ctx._get_assembly(":top")
    assert top is not None
    return asyncio.run(
        top.get_bom_detailed_async(ctx if with_context else None, stop_at_purchasable=stop_at_purchasable)
    )


def test_bom_detailed_flattens_the_whole_tree():
    """Without the option, every sub-assembly is expanded into its parts."""
    bom = _bom()

    # Two units of two cubes, one panel of three, and one loose cube.
    assert sorted(bom.keys()) == [CUBE]
    assert bom[CUBE]["count"] == 8
    assert bom[CUBE]["kind"] == "part"
    assert bom[CUBE]["desc"] == "A cube"


def test_bom_detailed_carries_the_store_data(store):
    """A line item says what to order, not only how many are needed."""
    bom = _bom(stop_at_purchasable=True)

    assert bom[UNIT]["vendor"] == "partcad"
    assert bom[UNIT]["sku"] == "UNIT-1"
    assert bom[UNIT]["count_per_sku"] == 1
    # The cube is not sold on its own, so it carries no store data.
    assert bom[CUBE]["vendor"] is None
    assert bom[CUBE]["sku"] is None


def test_bom_detailed_stops_at_a_purchasable_sub_assembly(store):
    """A sub-assembly that can be bought whole is a line item, not a parts list."""
    bom = _bom(stop_at_purchasable=True)

    assert sorted(bom.keys()) == [CUBE, UNIT]
    # The unit is bought twice; the cubes inside it are not listed at all.
    assert bom[UNIT]["count"] == 2
    assert bom[UNIT]["kind"] == "assembly"
    # Three cubes from the panel, which is not in stock, plus the loose one.
    assert bom[CUBE]["count"] == 4


def test_bom_detailed_expands_what_no_supplier_has(store):
    """A vendor and an SKU alone do not make a sub-assembly purchasable.

    The panel declares both, but the store has none in stock, so it is still
    something to assemble: it is expanded, and is not a line item of its own.
    """
    bom = _bom(stop_at_purchasable=True)

    assert PANEL not in bom


def test_bom_detailed_without_a_context_buys_nothing(store):
    """Suppliers cannot be queried without a context, so nothing is purchasable."""
    bom = _bom(stop_at_purchasable=True, with_context=False)

    assert sorted(bom.keys()) == [CUBE]
    assert bom[CUBE]["count"] == 8


def test_bom_detailed_matches_the_flat_bom():
    """The counts are the ones 'get_bom()' has always reported."""
    ctx = pc.Context(DATA)
    top = ctx._get_assembly(":top")
    flat = asyncio.run(top.get_bom())
    detailed = asyncio.run(top.get_bom_detailed_async(ctx))

    assert {name: entry["count"] for name, entry in detailed.items()} == flat
