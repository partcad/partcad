#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from ..assembly import Assembly
from ..sketch import Sketch
from .test import Test


class DegenerateTest(Test):
    """Fail a shape that came out with no size to it.

    A part can instantiate perfectly and still be wrong in a way nothing looks
    at: geometry that resolves to a sheet, a sliver or nothing at all. The
    'cad' test asks whether a shape was produced, not whether what was produced
    is a solid anybody meant.

    The failure this is written for came from a repository plugin that meshes
    LDraw parts. A part is mostly references, and a subfile that could not be
    fetched was skipped in silence, so a 2 x 2 round brick 9.6 mm tall meshed
    into a flat disc about a millimetre thick. It rendered; it exported; it
    passed every test there was. Only a picture showed it, and only because the
    towers built out of it looked wrong.

    So: a shape whose bounding box is empty, or which is flat to within a
    thousandth of a millimetre in any direction, is reported. A genuinely flat
    object - a sketch, a decal, a shim - says so:

        parts:
          shim:
            degenerate:
              skip: true
    """

    def __init__(self) -> None:
        super().__init__("degenerate")

    def cache_key_suffix(self, ctx, shape) -> str:
        # Whatever decides the verdict has to be in the key, or changing the
        # tolerance hands back the answer from the old one.
        config = (shape.config or {}).get("degenerate") or {}
        return ",skip=%s,tolerance=%s" % (
            bool(config.get("skip", False)),
            config.get("tolerance", 1e-3),
        )

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        config = (shape.config or {}).get("degenerate") or {}
        if config.get("skip", False):
            self.debug(shape, "Skipped by configuration")
            return self.TEST_PASSED

        # A sketch is flat because that is what a sketch is. Measuring one
        # against a rule about having size in every direction fails it for
        # being what it was asked to be, and a check an object cannot pass and
        # should not be taking is worse than no check.
        if isinstance(shape, Sketch):
            self.debug(shape, "Not applicable: a sketch is flat by definition")
            return self.TEST_PASSED

        # An assembly is checked through its parts, each of which is tested in
        # its own right; an assembly's own box says nothing about them.
        if isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            # A shape that did not build has no size for the same reason it has
            # nothing else, and 'cad' reports that. Measuring it would produce
            # a second failure naming a cause that is not the cause - "it is
            # empty" for a part whose script raised an ImportError - and send
            # the reader after the wrong thing.
            if await shape.get_wrapped(ctx) is None:
                test_ctx[self.NOT_CACHEABLE] = True
                self.debug(shape, "The shape did not build; that is the 'cad' test's to report")
                return self.TEST_PASSED

            box = await shape.get_bounding_box_async(ctx)
        except Exception as e:
            # About the machine, not the shape: do not remember it.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to measure: %s" % e)
            return self.TEST_PASSED

        if box is None:
            return self.failed(
                shape,
                "The shape built but occupies no space at all: its bounding box "
                "is empty.",
            )

        tolerance = float(config.get("tolerance", 1e-3))
        x_min, y_min, z_min, x_max, y_max, z_max = box
        extents = (x_max - x_min, y_max - y_min, z_max - z_min)
        flat = [axis for axis, extent in zip("XYZ", extents) if extent <= tolerance]
        if flat:
            return self.failed(
                shape,
                "The shape is flat in %s (%.4f x %.4f x %.4f mm): geometry is "
                "missing, or this is not a solid" % (" and ".join(flat), *extents),
            )
        return self.passed(shape)
