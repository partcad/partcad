#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A part with manufacturing instructions is made, and procured as its stock.

Whoever builds an assembly is taken at their word that they can follow a part's
manufacturing instructions. So such a part is not something to ask a supplier
for: what has to be procured is what it is made *from*, followed down the chain
(a bracket bent from a blank cut from a sheet is procured as the sheet), and
that is what the bills of materials list, what the cart holds, and what the
manufacturability test checks the suppliers for. A part that can be both
bought and made is tried as bought first.
"""

import asyncio

import pytest

import partcad as pc
from partcad import procurement
from partcad.manufacturing_instructions import describe
from partcad.part_config import PartConfiguration
from partcad.plugin_provider_data_cart import ProviderCart
from partcad.test import manufacturability
from partcad.test.test import Test

PACKAGE = "tests/partcad/unit/data/made_from_stock/partcad.yaml"
PROVIDER_NAME = "//:store"


class _Provider:
    """A provider that answers without a sandbox, and remembers what it was asked."""

    def __init__(self, available: set, asked: list) -> None:
        self.name = PROVIDER_NAME
        self.available = available
        self.asked = asked

    async def is_part_available(self, cart_item) -> bool:
        self.asked.append(cart_item.name)
        return cart_item.name in self.available


def _context(available=("//:sheet", "//:spacer")):
    ctx = pc.Context(PACKAGE)
    asked = []

    async def find_part_suppliers(cart_item, cart=None):
        return [PROVIDER_NAME]

    ctx.find_part_suppliers = find_part_suppliers
    ctx.get_provider = lambda name, params=None: _Provider(set(available), asked)
    ctx.asked = asked
    return ctx


def _part(ctx, name):
    return ctx._get_part("//:" + name)


#
# What each part is procured as
#


@pytest.mark.parametrize(
    "name, procured",
    [
        ("sheet", ["//:sheet"]),  # bought
        ("blank", ["//:sheet"]),  # made from the sheet
        ("bracket", ["//:sheet"]),  # bent from the blank, which is cut from the sheet
        ("knob", []),  # made from nothing it names
        ("spacer", ["//:spacer"]),  # both: bought first
        ("plate", ["//:plate"]),  # neither: procured as itself, to fail where it is seen
    ],
)
def test_what_a_part_is_procured_as(name, procured):
    ctx = _context()
    assert asyncio.run(procurement.procured_as(ctx, _part(ctx, name))) == procured


def test_a_missing_stock_is_kept_as_the_name_it_was_written_as():
    """So that the cart and the test say it is missing, rather than dropping the part."""
    ctx = _context()
    blank = _part(ctx, "blank")
    blank.config = dict(blank.config, manufacturing={"method": "subtractive", "source": "gone"})
    assert asyncio.run(procurement.procured_as(ctx, blank)) == ["//:gone"]


#
# The bills of materials
#


def test_the_supply_bom_is_what_has_to_be_bought():
    ctx = _context()
    kit = ctx._get_assembly("//:kit")
    # One sheet per part made from it: two brackets and a blank.
    assert asyncio.run(kit.get_supply_bom(ctx)) == {"//:sheet": 3, "//:spacer": 1, "//:plate": 1}


def test_without_a_context_the_supply_bom_is_what_has_to_be_had():
    """What the manufacturability test walks: a made part is something it tests too."""
    ctx = _context()
    kit = ctx._get_assembly("//:kit")
    assert asyncio.run(kit.get_supply_bom()) == {
        "//:bracket": 2,
        "//:blank": 1,
        "//:knob": 1,
        "//:spacer": 1,
        "//:plate": 1,
    }


def test_the_grouped_bom_lists_the_stock_and_what_is_made():
    ctx = _context()
    grouped = asyncio.run(ctx._get_assembly("//:kit").get_bom_grouped_async(ctx))

    stock = grouped["stock"]["//"]
    assert list(stock) == ["sheet"]
    assert stock["sheet"]["count"] == 3
    assert sorted(stock["sheet"]["for"]) == ["//:blank", "//:bracket"]
    assert stock["sheet"]["desc"] == "A sheet somebody sells"

    made = grouped["manufactured"]["//"]
    assert {name: entry["count"] for name, entry in made.items()} == {"bracket": 2, "blank": 1, "knob": 1}
    # What each one is made from as its instructions say, not the end of the chain.
    assert made["bracket"]["stock"] == "//:blank"
    assert made["knob"]["stock"] is None
    # Every part still goes into the assembly, however it is had.
    assert set(grouped["parts"]["//"]) == {"bracket", "blank", "knob", "spacer", "plate"}


def test_the_detailed_bom_orders_the_stock_by_its_sku():
    ctx = _context()
    bom = asyncio.run(ctx._get_assembly("//:kit").get_bom_detailed_async(ctx))
    sheet = bom["//:sheet"]
    assert (sheet["kind"], sheet["count"], sheet["vendor"], sheet["sku"]) == ("stock", 3, "acme", "SHEET-1")
    assert bom["//:bracket"]["madeFrom"] == "//:blank"
    assert "madeFrom" not in bom["//:spacer"]


def test_the_cart_holds_the_stock_of_a_part_that_is_made():
    ctx = _context()
    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, "//:bracket#2"))
    assert {name: item.count for name, item in cart.parts.items()} == {"//:sheet": 2}

    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, "//:kit"))
    assert {name: item.count for name, item in cart.parts.items()} == {"//:sheet": 3, "//:spacer": 1, "//:plate": 1}


#
# The manufacturability test
#


def _verdict(ctx, name):
    check = manufacturability.ManufacturabilityTest()
    return asyncio.run(check.test_part([check], ctx, _part(ctx, name)))


def test_a_made_part_is_believed_and_its_stock_is_checked():
    ctx = _context()
    assert _verdict(ctx, "bracket") == Test.TEST_PASSED
    # Nobody was asked for the bracket or the blank: they are made. The sheet
    # at the end of the chain is what somebody has to carry.
    assert set(ctx.asked) == {"//:sheet"}


def test_a_made_part_fails_when_its_stock_cannot_be_had(caplog):
    ctx = _context(available=())
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "blank") == Test.TEST_FAILED
    assert "The stock '//:sheet' it is made from cannot be had" in caplog.text


def test_a_part_made_from_nothing_it_names_needs_nothing_procured():
    ctx = _context(available=())
    assert _verdict(ctx, "knob") == Test.TEST_PASSED
    assert ctx.asked == []


def test_a_part_that_is_both_is_bought_when_it_can_be():
    ctx = _context(available=("//:spacer",))
    assert _verdict(ctx, "spacer") == Test.TEST_PASSED
    # Procurement answered, so making it was never looked into.
    assert ctx.asked == ["//:spacer"]


def test_a_part_that_is_both_is_made_when_it_cannot_be_bought():
    ctx = _context(available=("//:sheet",))
    assert _verdict(ctx, "spacer") == Test.TEST_PASSED
    assert ctx.asked == ["//:spacer", "//:sheet"]

    ctx = _context(available=())
    assert _verdict(ctx, "spacer") == Test.TEST_FAILED


def test_a_part_that_is_only_bought_still_needs_a_supplier():
    ctx = _context(available=())
    assert _verdict(ctx, "sheet") == Test.TEST_FAILED


#
# The instructions the book repeats
#


def test_the_instructions_are_the_declaration_read_back():
    ctx = _context()
    lines = describe(PartConfiguration.get_manufacturing_data(_part(ctx, "blank")), "//:sheet")
    assert lines == [
        "Made by taking material away from `//:sheet`.",
        "Make it on a laser cutter, working along -Z; kerf 0.2 mm.",
    ]
    lines = describe(PartConfiguration.get_manufacturing_data(_part(ctx, "bracket")))
    assert lines == ["Bent from `blank`, along the bends drawn in `bends`."]


def test_a_saw_cut_is_said_in_millimetres_and_inches():
    from partcad.part_config_manufacturing import PartConfigManufacturing

    data = PartConfigManufacturing(
        {
            "parameters": {"length": {"type": "float", "default": 29.28125}},
            "manufacturing": {
                "method": "subtractive",
                "source": "board",
                "cut": {"cuts": [{"along": "+Y", "length": "$length in"}, {"plane": [[0, 0, 10], "-Z"]}]},
            },
        }
    )
    assert describe(data) == [
        "Made by taking material away from `board`.",
        "Cut it to size with a saw:",
        "1. Cut across Y, 743.744 mm (29.281 in) from the -Y end of the stock.",
        "2. Cut along the plane through (0, 0, 10) mm facing (0, 0, -1); what is on the side it faces is the offcut.",
    ]


def test_a_part_whose_stock_is_missing_is_reported_by_the_cart():
    """Named, as the stock of the part that names it -- not an assertion failure."""
    ctx = _context()
    blank = _part(ctx, "blank")
    blank.config = dict(blank.config, manufacturing={"method": "subtractive", "source": "gone"})
    with pytest.raises(ValueError, match="'//:gone', which '//:blank' is made from, is not found"):
        asyncio.run(ProviderCart().add_object(ctx, "//:blank"))
