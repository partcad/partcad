#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from ..assembly import Assembly


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

    A shape holding no solid at all - a sketch, a shell, a wire - is not inside
    out and is passed over. A part that is genuinely built as a void, if such a
    thing is wanted, says so:

        parts:
          cavity:
            solidity:
              skip: true
    """

    def __init__(self) -> None:
        super().__init__("solidity")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        config = (shape.config or {}).get("solidity") or {}
        if config.get("skip", False):
            self.debug(shape, "Skipped by configuration")
            return self.TEST_PASSED

        # An assembly is checked through its parts, each tested in its own
        # right; the compound of a set of parts says nothing they do not.
        if isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            result = await shape.get_solidity_async(ctx)
        except Exception as e:
            # A shape that will not build is what the 'cad' test is for.
            self.debug(shape, "Failed to check: %s" % e)
            return self.TEST_PASSED

        if result is None:
            self.debug(shape, "The shape produced no geometry to check")
            return self.TEST_PASSED

        if not result.get("solids"):
            self.debug(shape, "No solid to check: a sketch, a shell or a wire")
            return self.TEST_PASSED

        volume = result.get("volume")
        if volume is not None and volume < 0.0:
            return self.failed(
                shape,
                "The shape is inside out: its volume measures %.3f mm^3, which is "
                "negative because its faces are oriented inward. It will render "
                "correctly and every boolean against it will be wrong." % volume,
            )

        if result.get("valid") is False:
            return self.failed(
                shape,
                "The shape is not a valid solid, so booleans against it - "
                "interference, CAM, FEA - cannot be relied on.",
            )

        return self.passed(shape)
