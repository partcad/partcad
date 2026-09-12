#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from ..assembly import Assembly
from ..sketch import Sketch


class SolidityTest(Test):
    """Fail a part that is inside out.

    A solid's faces are oriented: outward for material on the inside of them,
    inward for material outside. Get that backwards and the shape still builds,
    still renders, still exports, and still measures the right size - a picture
    of it is indistinguishable from a picture of the right thing. What breaks is
    the arithmetic. OCCT reports such a solid's volume as negative, and every
    boolean against it returns a number with no relation to any shape.

    This was found in LDraw parts meshed from triangles: LDraw declares winding
    per file with its BFC metadata, the mesher ignored it, and every LEGO part
    came out inverted. Brick 2 x 4 measured -1939.6 mm^3, and two copies of it
    100 mm apart - sharing, necessarily, nothing - intersected to 2282 mm^3.
    Nothing reported it, because nothing asked. Anything built on booleans is
    wrong on such a part: interference, CAM, FEA, the volume in a bill of
    materials.

    What this does not fail is a solid that is merely not *valid*. Plenty of
    usable geometry is not, and intersects perfectly well regardless; failing
    it would condemn an entire library that works. That is reported and passed.

    A shape holding no solid at all - a sketch, a shell, a wire - is not inside
    out and is passed over. That is decided on what the shape *is*, not on what
    it asks for: there is no way for a part to turn this check off. A solid of
    negative volume is broken whatever it was meant to be, and a check an object
    can exclude itself from is a check that reports on the objects that did not
    need checking.
    """

    def __init__(self) -> None:
        super().__init__("solidity")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        # A sketch has no solid to be the wrong way out, and asking costs a
        # sandbox each time. Answered here rather than by measuring.
        if isinstance(shape, Sketch):
            self.debug(shape, "Not applicable: a sketch has no solid")
            return self.TEST_PASSED

        # An assembly is checked through its parts, each tested in its own
        # right; the compound of a set of parts says nothing they do not.
        if isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            result = await shape.get_solidity_async(ctx)
        except Exception as e:
            # A shape that will not build is what the 'cad' test is for. This
            # verdict is about the machine rather than the shape, so it must
            # not be remembered: installing what was missing would not change
            # the key it would be read back under.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to check: %s" % e)
            return self.TEST_PASSED

        if result is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The shape produced no geometry to check")
            return self.TEST_PASSED

        if not result.get("solids"):
            self.debug(shape, "No solid to check: a sketch, a shell or a wire")
            return self.TEST_PASSED

        # The least of the solids, not their sum: a compound holding one
        # inverted solid and a larger correct one adds up to a positive number,
        # and the inversion disappears into the total.
        volume = result.get("min_solid_volume")
        if volume is None:
            volume = result.get("volume")
        # Non-positive, not negative. A solid of exactly zero volume is not a
        # solid either, and it is the boundary a mesh that collapses lands on.
        if volume is not None and volume <= 0.0:
            return self.failed(
                shape,
                "The shape is not a solid anything can be computed from: a "
                "constituent solid measures %.3f mm^3. A negative volume means "
                "its faces are oriented inward; zero means it encloses nothing. "
                "It will render correctly and every boolean against it will be "
                "wrong." % volume,
            )

        # Not a failure. Plenty of usable geometry is not a valid solid in
        # OCCT's sense and behaves perfectly well: an LDraw brick is an open
        # mesh - a stud is a cylinder and a top disc with no bottom, resting on
        # a face the parent never cuts - so it has hundreds of free boundary
        # edges and fails IsValid, while two copies of it 100 mm apart
        # correctly share no volume at all. Failing on validity would condemn
        # every part of a whole library that works. It is said, once, because
        # it does narrow what can be relied on.
        if result.get("valid") is False:
            self.info(
                shape,
                "The shape is a solid the right way out, but not a valid one: "
                "expect open edges, and check any boolean result against it.",
            )

        return self.passed(shape)
