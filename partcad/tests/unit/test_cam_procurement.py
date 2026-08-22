#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""'pc test' asks for the same objects 'pc supply' would order.

The manufacturability test used to walk 'get_bom()', the flattened list of an
assembly's parts, so the parts of a sub-assembly that is sold assembled had to
be manufacturable by themselves -- something nobody buying that sub-assembly
would ever need. It walks the procurement BoM instead now, and verifies that a
purchasable assembly has a supplier, the way it always has for a part.
"""

import asyncio

import partcad as pc
from partcad.test import cam
from partcad.test.test import Test

# The same package the cart tests use: '//sub:unit' is a pair of cubes sold
# assembled, '//sub:frame' is a cube plus an embedded assembly holding a bolt
# and a '//sub:unit', and '//:top' is two units, a frame and a loose cube.
SUPPLY_BOM_PACKAGE = "partcad/tests/unit/data/supply_bom/partcad.yaml"

PROVIDER_NAME = "//sub:store"


class _Recorder(Test):
    """A stand-in test that records what it is handed, and passes"""

    def __init__(self) -> None:
        super().__init__("recorder")
        self.seen = []

    async def test(self, tests_to_run, ctx, shape, test_ctx: dict = {}) -> bool:
        self.seen.append(f"{shape.project_name}:{shape.name}")
        return self.TEST_PASSED


class _Provider:
    """A provider that answers without a sandbox, unlike a real one"""

    def __init__(self, available: bool) -> None:
        self.name = PROVIDER_NAME
        self.available = available

    async def is_part_available(self, cart_item) -> bool:
        return self.available


def _context(suppliers=(PROVIDER_NAME,), available=True):
    """A context whose supplier lookup is answered locally"""
    ctx = pc.Context(SUPPLY_BOM_PACKAGE)

    async def find_part_suppliers(cart_item, cart=None):
        return list(suppliers)

    ctx.find_part_suppliers = find_part_suppliers
    ctx.get_provider = lambda name, params=None: _Provider(available)
    return ctx


def test_walks_the_procurement_bom():
    """The objects tested are the ones a cart would hold, not every last part"""
    ctx = _context()
    top = ctx._get_assembly("//:top")
    assert top is not None

    recorder = _Recorder()
    asyncio.run(cam.CamTest().test_assembly([recorder], ctx, top))

    # '//sub:unit' is handed over as itself. Walking 'get_bom()' instead would
    # have listed the cubes inside it and never mentioned the unit at all.
    assert sorted(recorder.seen) == ["//sub:bolt", "//sub:cube", "//sub:unit"]


def test_purchasable_assembly_is_not_taken_apart():
    """An assembly that is bought assembled passes on its own merits"""
    ctx = _context()
    unit = ctx._get_assembly("//sub:unit")
    assert unit is not None

    recorder = _Recorder()
    test = cam.CamTest()
    assert asyncio.run(test.test([test, recorder], ctx, unit)) == Test.TEST_PASSED

    # It has no 'manufacturing' section and its cubes were never asked about:
    # somebody sells it, so what is inside it is their problem.
    assert recorder.seen == []


def test_purchasable_assembly_without_a_supplier_fails():
    """Being for sale is not enough: somebody has to actually carry it"""
    ctx = _context(suppliers=())
    unit = ctx._get_assembly("//sub:unit")
    assert unit is not None

    test = cam.CamTest()
    assert asyncio.run(test.test([test], ctx, unit)) == Test.TEST_FAILED


def test_purchasable_assembly_no_provider_carries_it():
    """A supplier that does not stock the SKU does not count either"""
    ctx = _context(available=False)
    unit = ctx._get_assembly("//sub:unit")
    assert unit is not None

    test = cam.CamTest()
    assert asyncio.run(test.test([test], ctx, unit)) == Test.TEST_FAILED


def test_supply_failure_names_the_kind():
    """The reason a supplier check failed says what could not be supplied"""
    ctx = _context(available=False)
    test = cam.CamTest()

    part = ctx._get_part("//sub:bolt")
    assert asyncio.run(test.supply_failure(ctx, part)) == "No suppliers provide the part"

    unit = ctx._get_assembly("//sub:unit")
    assert asyncio.run(test.supply_failure(ctx, unit)) == "No suppliers provide the assembly"

    ctx_without_suppliers = _context(suppliers=())
    assert asyncio.run(test.supply_failure(ctx_without_suppliers, part)) == "No suppliers found"


def test_assembly_nobody_sells_is_still_taken_apart():
    """An assembly without a vendor is procured as its contents"""
    ctx = _context()
    frame = ctx._get_assembly("//sub:frame")
    assert frame is not None

    recorder = _Recorder()
    asyncio.run(cam.CamTest().test_assembly([recorder], ctx, frame))

    # The assembly embedded in 'frame.assy' is not an object of any package, so
    # its contents are what gets tested.
    assert sorted(recorder.seen) == ["//sub:bolt", "//sub:cube", "//sub:unit"]
