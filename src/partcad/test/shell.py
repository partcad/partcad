#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import brep_inspect
from ..assembly import Assembly
from ..sketch import Sketch
from .test import Test


class ShellTest(Test):
    """Fail a part that came back as a skin rather than as a body.

    A shell is a set of faces joined along their edges, with nothing said about
    which side of them is material. A solid is a shell that has been declared to
    bound a volume, and that declaration is the whole difference. It changes
    nothing about how the shape looks and everything about what can be computed
    from it: two 10 mm cubes overlapping by 5 mm share 500 mm^3 and add up to
    1500, and asking OCCT for either against the second one's shell returns a
    result with no solid in it and a volume of zero. So a part that is a shell
    builds, renders, exports and measures its right size, and is useless for
    everything downstream of a boolean - interference, CAM, FEA, the mass in a
    bill of materials. Like the two checks beside it, this is about a part that
    looks entirely correct in a picture.

    'solidity' does not catch it, and cannot: it counts the solids in a shape
    and has nothing to say about a shape that holds none. That is the hole this
    fills - "no solid to check" was as far as anything looked.

    PartCAD's wrappers convert a closed shell into the solid it already bounds,
    so that a script returning 'Shell' produces the part it meant (see
    'wrappers/wrapper_common.solidify'). Two kinds of shell get past that. One
    does not close: its faces enclose nothing, so there is no solid to declare
    and nothing to compute either way. The other comes from a part type that
    hands over what it was given rather than deciding what it should be - a STEP
    or a BREP file, where a surface model is what the file says the part is, and
    saying so is this check's job rather than quietly changing it.

    Read off the BREP bytes rather than measured in a sandbox: the payload the
    core already holds says which shapes it is made of in plain text, and
    'partcad.brep_inspect' reads that without a CAD kernel. So this check costs
    no sandbox and no interpreter, which is why it can be asked of every part.

    A shell a solid bounds is not reported - a box has one, and it is that box's
    boundary. What is reported is a shell no solid owns: the shape itself, or one
    inside the compound it is.

    There is no way for a part to turn this off. A part that is a surface is not
    a part somebody can compute with, whatever it was meant to be, and a check an
    object can exclude itself from is a check that reports on the objects that
    did not need checking. The verdict is a fact about the geometry; what to do
    about a part that fails is a decision to take on the part.
    """

    def __init__(self) -> None:
        super().__init__("shell")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        # A sketch is made of edges, wires and faces, and a shell is not one of
        # the things it can be: the sketch factories keep the faces out of a
        # shell rather than the shell (see wrapper_common.combine). Failing one
        # for not being a body would fail it for being a sketch.
        if isinstance(shape, Sketch):
            self.debug(shape, "Not applicable: a sketch is not a body")
            return self.TEST_PASSED

        # An assembly is checked through its parts, each tested in its own
        # right; the compound of a set of parts says nothing they do not.
        if isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            envelope = await shape.get_wrapped(ctx)
        except Exception as e:
            # A shape that will not build is what the 'cad' test is for, and a
            # second failure naming a cause that is not the cause sends the
            # reader after the wrong thing. About the build rather than the
            # shape, so it must not be remembered.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to read: %s" % e)
            return self.TEST_PASSED

        if envelope is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The shape did not build; that is the 'cad' test's to report")
            return self.TEST_PASSED

        free_shells, unread = brep_inspect.envelope_free_shells(envelope)

        if free_shells:
            return self.failed(
                shape,
                "The shape is a skin rather than a body: %d shell(s) that no "
                "solid bounds itself with. It renders, exports and measures its "
                "right size, and every boolean against it comes back with no "
                "solid in it - so interference, CAM, FEA and any mass computed "
                "from it are wrong. A shell a script returns is closed into a "
                "solid automatically, so either these faces enclose nothing or "
                "they come from a file that states the part as a surface." % free_shells,
            )

        if unread:
            # Nothing was read, so nothing is known: neither a pass to remember
            # nor a failure to report. It is about the payload rather than the
            # shape, and installing whatever would read it does not change the
            # key this would be read back under.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "%d payload(s) could not be read; nothing to report" % unread)
            return self.TEST_PASSED

        return self.passed(shape)
