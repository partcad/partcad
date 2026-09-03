#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import jsonschema
import yaml

import partcad as pc
from partcad.assembly import Assembly
from partcad.plugin_provider_data_cart import ProviderCart, resolve_cart_object

# A package where some of the objects are sold assembled:
#   '//sub:unit'  - a pair of cubes, sold assembled
#   '//sub:frame' - a cube plus an embedded assembly of a bolt and a '//sub:unit',
#                   which nobody sells assembled
#   '//:top'      - two '//sub:unit', one '//sub:frame' and one loose cube
SUPPLY_BOM_PACKAGE = "tests/partcad/unit/data/supply_bom/partcad.yaml"


def _cart(spec: str, recursive: bool = False) -> ProviderCart:
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)
    cart = ProviderCart()
    asyncio.run(cart.add_object(ctx, spec, recursive=recursive))
    return cart


def _counts(cart: ProviderCart) -> dict[str, int]:
    return {name: item.count for name, item in cart.parts.items()}


def test_supply_bom_stops_at_supplyable_assembly():
    """The procurement BoM lists an assembly that is sold assembled, not its contents"""
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)
    top = ctx._get_assembly("//:top")
    assert top is not None

    # Two units placed by 'top' itself, and one more inside 'frame'.
    assert asyncio.run(top.get_supply_bom()) == {
        "//sub:unit": 3,
        "//sub:cube": 2,
        "//sub:bolt": 1,
    }


def test_bom_still_flattens_everything():
    """'get_bom()' keeps flattening the whole tree into parts"""
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)
    top = ctx._get_assembly("//:top")
    assert top is not None

    # Each of the three units contributes a pair of cubes, on top of the cube
    # 'frame' places and the one 'top' places itself.
    assert asyncio.run(top.get_bom()) == {"//sub:cube": 8, "//sub:bolt": 1}


def test_supply_bom_matches_bom_where_nothing_is_sold_assembled():
    """The two walks agree on a package that has no purchasable assembly in it

    This is what keeps 'pc supply' and 'pc test' behaving exactly as they used
    to for every package written before assemblies could be bought at all.
    """
    ctx = pc.Context("tests/partcad/unit/data/assembly_bom/partcad.yaml")
    top = ctx._get_assembly("//:top")
    assert top is not None

    assert asyncio.run(top.get_supply_bom()) == asyncio.run(top.get_bom())


def test_cart_stops_at_supplyable_assembly():
    """By default the cart stops drilling down at the first assembly it can order"""
    assert _counts(_cart("//:top")) == {
        "//sub:unit": 3,
        "//sub:cube": 2,
        "//sub:bolt": 1,
    }


def test_cart_recursive_drills_down_to_parts():
    """'recursive' orders the parts even where the assembly itself is for sale"""
    assert _counts(_cart("//:top", recursive=True)) == {"//sub:cube": 8, "//sub:bolt": 1}


def test_cart_supplyable_assembly_asked_for_directly():
    """An assembly that is for sale is ordered as one item, unless asked to recurse"""
    assert _counts(_cart("//sub:unit")) == {"//sub:unit": 1}
    assert _counts(_cart("//sub:unit", recursive=True)) == {"//sub:cube": 2}


def test_cart_counts_multiply():
    """The requested count multiplies the contents, in either mode"""
    assert _counts(_cart("//:top#3")) == {
        "//sub:unit": 9,
        "//sub:cube": 6,
        "//sub:bolt": 3,
    }
    assert _counts(_cart("//:top#3", recursive=True)) == {"//sub:cube": 24, "//sub:bolt": 3}


def test_cart_item_carries_assembly_store_data():
    """An assembly in the cart is ordered by vendor and SKU, the way a part is"""
    item = _cart("//sub:unit").parts["//sub:unit"]
    assert item.vendor == "acme"
    assert item.sku == "UNIT-1"
    assert item.count_per_sku == 2

    composed = item.compose()
    assert composed["vendor"] == "acme"
    assert composed["sku"] == "UNIT-1"
    assert composed["count_per_sku"] == 2


def test_cart_item_rebuilt_from_its_name():
    """A cart item survives being reduced to its name and count

    'Context.prepare_supplier_carts()' rebuilds every item that way when it
    splits a cart per supplier, so an assembly has to be resolvable by name.
    """
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)
    cart = ProviderCart()
    item = asyncio.run(cart.add_part_spec(ctx, "//sub:unit#3"))

    assert item.name == "//sub:unit"
    assert item.count == 3
    assert item.sku == "UNIT-1"


def test_resolve_cart_object():
    """A cart item name resolves to a part or to an assembly"""
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)
    assert resolve_cart_object(ctx, "//sub:cube").kind == "part"
    assert resolve_cart_object(ctx, "//sub:unit").kind == "assembly"
    assert resolve_cart_object(ctx, "//sub:nonexistent") is None


def test_purchasable_requires_both_vendor_and_sku():
    """Neither the vendor nor the SKU is enough to order anything on its own"""
    from partcad.shape_config_store import ShapeConfigStore

    assert ShapeConfigStore({"vendor": "acme", "sku": "UNIT-1"}).is_purchasable
    assert not ShapeConfigStore({"vendor": "acme"}).is_purchasable
    assert not ShapeConfigStore({"sku": "UNIT-1"}).is_purchasable
    assert not ShapeConfigStore({}).is_purchasable

    # The default pack size is one
    assert ShapeConfigStore({}).count_per_sku == 1


def test_embedded_assembly_is_never_supplied():
    """An assembly embedded in its parent's source file is not orderable

    It is not an object of any package, so there would be no name to order it
    by, no matter what it declares about a vendor.
    """
    embedded = Assembly(
        "//sub",
        {"name": "frame:cluster", "child": True, "vendor": "acme", "sku": "CLUSTER-1"},
    )
    assert embedded.get_store_data().is_purchasable
    assert not embedded.is_declared_purchasable()

    # ... so the cart procures what is inside it instead.
    assert _counts(_cart("//sub:frame")) == {
        "//sub:cube": 1,
        "//sub:bolt": 1,
        "//sub:unit": 1,
    }


def test_fixture_packages_pass_the_schema():
    """The purchasable objects these tests rely on are valid configuration

    'SchemaLinting' validates every 'partcad.yaml' against the packaged schema,
    so a key the code reads has to be a key the schema allows -- for assemblies
    as well as for parts.
    """
    from partcad.lint.all import get_partcad_schema

    schema = get_partcad_schema()

    for path in (SUPPLY_BOM_PACKAGE, "tests/partcad/unit/data/supply_bom/sub/partcad.yaml"):
        with open(path) as file:
            jsonschema.validate(instance=yaml.safe_load(file.read()), schema=schema)
