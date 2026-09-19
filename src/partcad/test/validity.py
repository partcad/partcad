#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from ..assembly import Assembly
from ..sketch import Sketch
from .test import Test


class ValidityTest(Test):
    """Report a part whose geometry OCCT will not certify.

    'BRepCheck_Analyzer' asks whether a shape is well formed in OCCT's terms:
    edges that close the faces they border, faces that meet along them, no
    self-intersections, orientations that agree. A shape can be a solid of
    honest positive volume and still fail it - an LDraw brick meshed from
    triangles is a solid, measures 1706 mm^3, intersects other parts correctly,
    and carries 224 free boundary edges that this rejects.

    Which is why this reports rather than fails, alone among the geometry
    checks. The parts it has most to say about are ones nothing is functionally
    wrong with, and a red build over them would say something untrue. What it
    does say is that the geometry has defects, so that a boolean that comes back
    strange, a mesh that will not print or a CAM path that wanders has somewhere
    to start.

    It sits beside two checks that do fail, and the three ask different
    questions of the same shape. 'solidity' asks which way the faces point - a
    negative volume is inside out, and every boolean against it is nonsense.
    'shell' asks whether there is a body at all - a skin bounds nothing, and a
    boolean against it returns nothing. This one asks whether the body, however
    it points, is built cleanly. A part can pass either of the others and fail
    this, which is the reason it is a check of its own rather than a line in
    one of them.

    Silenced per object where the defects are known and accepted:

        parts:
          meshed_import:
            validity:
              skip: true
    """

    def __init__(self) -> None:
        super().__init__("validity")

    async def cache_key_suffix(self, ctx, shape) -> str:
        config = (shape.config or {}).get("validity") or {}
        return ",skip=%s" % bool(config.get("skip", False))

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        config = (shape.config or {}).get("validity") or {}
        if config.get("skip", False):
            self.debug(shape, "Skipped by configuration")
            return self.TEST_PASSED

        # A sketch is edges, wires and faces; 'well formed solid' is not a
        # question it has an answer to.
        if isinstance(shape, Sketch):
            self.debug(shape, "Not applicable: a sketch is not a body")
            return self.TEST_PASSED

        # An assembly is checked through its parts, each in its own right.
        if isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            result = await shape.get_solidity_async(ctx)
        except Exception as e:
            # Reaching here means this check broke rather than that the shape
            # is sound, so it is not remembered - but it is not failed either,
            # because this check does not fail. Said at info, where a reader
            # will see that the question went unanswered.
            test_ctx[self.NOT_CACHEABLE] = True
            self.info(shape, "could not be checked: %s" % e)
            return self.TEST_PASSED

        if result is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The shape did not build; that is the 'cad' test's to report")
            return self.TEST_PASSED

        if not result.get("solids"):
            # No body to certify. Whether that is a fault is 'shell's question.
            self.debug(shape, "No solid to check; 'shell' reports that")
            return self.TEST_PASSED

        if result.get("valid") is False:
            self.info(
                shape,
                "the geometry is a solid but not a well formed one: OCCT will "
                "not certify it. Expect trouble from anything exacting - "
                "booleans, meshing for print, CAM - and treat a strange result "
                "from those as this rather than as the tool.",
            )

        return self.passed(shape)
