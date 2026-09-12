#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from ..assembly import Assembly
from .test import Test


class InterferenceTest(Test):
    """Fail an assembly whose parts share space.

    The 'cad' test passes an assembly whose parts are all in the wrong place -
    it only asks whether the geometry instantiates. This asks where the parts
    ended up, which is the question an assembly is actually judged on, and the
    one nothing has been able to answer without a person looking at a render.

    The answer comes from a boolean common and the volume of what it produces.
    Bounding boxes are not enough: two boxes meeting says very little about two
    solids - a bracket around a shaft, an L around a corner, anything rotated -
    so they are used only to choose the pairs worth intersecting.

    What counts as sharing space is a threshold rather than 'any volume at all'.
    Parts meant to go together touch, and meshed geometry touching produces
    slivers, so an assembly that fits would otherwise fail. The default asks for
    a cubic millimetre; a package that wants to be stricter or looser can say so:

        assemblies:
          gearbox:
            interference:
              minVolume: 0.5      # mm^3 of shared space before it is reported
              minFraction: 0.01   # ...and/or that share of the smaller part
              ignore:             # pairs that are meant to interfere
                - [shaft, hub]
    """

    def __init__(self) -> None:
        super().__init__("interference")

    def cache_key_suffix(self, ctx, shape) -> str:
        config = (shape.config or {}).get("interference") or {}
        return ",skip=%s,minVolume=%s,minFraction=%s,ignore=%s" % (
            bool(config.get("skip", False)),
            config.get("minVolume", 1.0),
            config.get("minFraction", 0.0),
            sorted(tuple(sorted(pair)) for pair in config.get("ignore", [])),
        )

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        config = (shape.config or {}).get("interference") or {}
        if config.get("skip", False):
            self.debug(shape, "Skipped by configuration")
            return self.TEST_PASSED

        try:
            result = await shape.get_interference_async(
                ctx,
                min_volume=float(config.get("minVolume", 1.0)),
                min_fraction=float(config.get("minFraction", 0.0)),
            )
        except Exception as e:
            # An assembly that will not realize is what the 'cad' test is for;
            # this one has nothing to say about it either way - and nothing
            # worth remembering, since the reason was not the assembly.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to check for interference: %s" % e)
            return self.TEST_PASSED

        if result is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The assembly produced no geometry to check")
            return self.TEST_PASSED

        # Said out loud rather than left to be inferred from a pass. A shape
        # that is not a valid solid cannot be intersected meaningfully - an
        # inside-out one "shares" volume with parts it is nowhere near - so it
        # is left out, and an assembly built entirely from such parts is not
        # being checked at all. Whoever reads a pass should know which it was.
        # A verdict reached while some of it could not be looked at is not a
        # verdict about the assembly, and remembering it would hand back a pass
        # that was never earned - without even repeating what went unexamined,
        # since a cached result is returned before the test runs.
        indeterminate = result.get("indeterminate") or []
        unchecked = result.get("unchecked") or []
        if indeterminate or unchecked:
            test_ctx[self.NOT_CACHEABLE] = True

        if unchecked:
            shown = ", ".join(unchecked[:5]) + ("..." if len(unchecked) > 5 else "")
            self.info(
                shape,
                "%d part(s) are not valid solids and were not checked: %s"
                % (len(unchecked), shown),
            )

        # A pair whose boolean did not come back is not a pair that does not
        # overlap. Saying so is the difference between a check that found
        # nothing and a check that could not look.
        for pair in indeterminate:
            self.info(
                shape,
                "could not decide whether '%s' and '%s' overlap: %s"
                % (pair["a"], pair["b"], pair.get("reason", "the boolean failed")),
            )

        overlaps = result.get("overlaps") or []

        ignored = {tuple(sorted(pair)) for pair in config.get("ignore", [])}
        reported = [o for o in overlaps if not _is_ignored(o, ignored)]
        if not reported:
            return self.passed(shape)

        for overlap in reported:
            self.failed(
                shape,
                "'%s' and '%s' share %.3f mm^3" % (overlap["a"], overlap["b"], overlap["volume"]),
            )
        return self.TEST_FAILED


def _is_ignored(overlap, ignored):
    """Whether this pair was declared as one that is meant to interfere.

    A pair is named by the two part names, in either order, and matches a
    child whose name ends with it - so 'shaft' covers 'gearbox/shaft' without
    the configuration having to spell out where in the tree it sits.
    """
    for a, b in ignored:
        names = (overlap["a"], overlap["b"])
        if _matches(names[0], a) and _matches(names[1], b):
            return True
        if _matches(names[0], b) and _matches(names[1], a):
            return True
    return False


def _matches(name, pattern):
    return name == pattern or name.endswith("/" + pattern)
