#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import surface as pc_surface
from ..assembly import Assembly
from ..sketch import Sketch
from .test import Test

# How thin, in millimetres, an object may be in one direction before it counts
# as flat. Not settable per object: see the class docstring.
TOLERANCE = 1e-3


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
    thousandth of a millimetre in any direction, is reported.

    There is no way for a part to turn this off. A part that measured a
    millimetre where it should have measured ten is broken whatever it says
    about itself, and a check an object can exclude itself from is a check that
    reports on the objects that did not need checking. A kind of object that is
    flat by nature is passed over here, on what it *is* rather than on what it
    asks for: that is what the clauses below do for a sketch, for an assembly,
    and for a part whose type builds a surface on purpose - a straight wall is
    as flat as a sheet of paper, because that is what it is (see
    'partcad.surface').
    """

    def __init__(self) -> None:
        super().__init__("degenerate")

    def inapplicable(self, shape):
        if isinstance(shape, Sketch):
            return "a sketch is flat by definition"
        if isinstance(shape, Assembly):
            return "an assembly is checked through its parts, each of which is tested in its own right"
        # A part that is a surface by its type - a wall - is one on purpose, and
        # is passed over on what it is, the way a sketch is: see 'partcad.surface'.
        return pc_surface.not_a_body(shape)

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        # A sketch is flat because that is what a sketch is. Measuring one
        # against a rule about having size in every direction fails it for
        # being what it was asked to be, and a check an object cannot pass and
        # should not be taking is worse than no check.
        if isinstance(shape, Sketch):
            return self.not_applicable(shape, self.inapplicable(shape))

        # An assembly is checked through its parts, each of which is tested in
        # its own right; an assembly's own box says nothing about them.
        if isinstance(shape, Assembly):
            return self.not_applicable(shape, self.inapplicable(shape))

        # A wall is a skin with no body to it, by its type: see 'partcad.surface'.
        if pc_surface.is_surface(shape):
            return self.not_applicable(shape, self.inapplicable(shape))

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
            # Not a pass: a shape that did not build was answered above, so
            # reaching here means this check broke.
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the degenerate check could not be run: %s" % e)

        if box is None:
            return self.failed(
                shape,
                "The shape built but occupies no space at all: its bounding box " "is empty.",
            )

        x_min, y_min, z_min, x_max, y_max, z_max = box
        extents = (x_max - x_min, y_max - y_min, z_max - z_min)
        flat = [axis for axis, extent in zip("XYZ", extents) if extent <= TOLERANCE]
        if flat:
            return self.failed(
                shape,
                "The shape is flat in %s (%.4f x %.4f x %.4f mm): geometry is "
                "missing, or this is not a solid" % (" and ".join(flat), *extents),
            )
        return self.passed(shape)
