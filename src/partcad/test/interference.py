#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from ..assembly import Assembly
from .test import Test

# The floor that separates a boolean's arithmetic noise from a real overlap.
# Two touching surfaces should answer zero and answer a sliver instead; this is
# above that and far below anything anyone would call an interference.
DEFAULT_MIN_VOLUME = 0.05


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

    The threshold exists to absorb arithmetic, and nothing else. Two surfaces
    that merely touch bound no volume between them, but a boolean over
    tessellated or imperfectly coincident faces answers with a sliver of a few
    thousandths of a cubic millimetre rather than with zero. The default floor
    is 0.05 mm^3: orders of magnitude below any overlap a person would call
    one, and above the noise.

    It is deliberately not a place to put anything else. An overlap that is
    meant to be there is a property of the joint between those two parts, and is
    read from that joint.

    Every one of them is read from the joint, and none is declared against the
    pair. Two parts have exactly one relationship - the 'connect' that joins
    them - so that is the only place a statement about the two of them can live
    and still be true when one of them moves, is renamed, or is used elsewhere.

    - an interface that declares 'selfScrew' cuts its own thread wherever it is
      used, so the two solids occupy the same space where that thread is formed;
    - a mating that declares 'selfScrew' says it of the pairing, which is the
      only place it can be said when neither end knows on its own: the same
      screw cuts its own thread in a pilot hole and cuts nothing in a clearance
      one;
    - a mating that declares 'snapIn' says the pairing is made by pushing one
      past the other rather than screwing it in - a bore onto a thread it is
      not cut to match, a LEGO stud into an anti-stud. Getting past means
      passing through, and a model that holds no springs holds them
      overlapping;
    - a connection whose 'how' declares either of those says it of this joint
      alone: an ordinary screw driven into soft material cuts a thread there
      too, which is a fact about the joint and not about the screw;
    - a connection's 'interferes' names the further items the same act of
      joining drives through, which nothing about the connection can imply: a
      bolt is connected to one part and passes through the three behind it.

    An overlap between two parts joined in any of those ways is expected, and
    is not reported. Every other overlap between them still is: a screw may
    bite the bracket it is driven into without also being inside the housing.

        assemblies:
          gearbox:
            interference:
              minVolume: 0.01     # a tighter floor, for geometry that is exact
    """

    def __init__(self) -> None:
        super().__init__("interference")

    async def cache_key_suffix(self, ctx, shape) -> str:
        config = (shape.config or {}).get("interference") or {}
        return ",skip=%s,minVolume=%s,minFraction=%s" % (
            bool(config.get("skip", False)),
            config.get("minVolume", DEFAULT_MIN_VOLUME),
            config.get("minFraction", 0.0),
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
                min_volume=float(config.get("minVolume", DEFAULT_MIN_VOLUME)),
                min_fraction=float(config.get("minFraction", 0.0)),
            )
        except Exception as e:
            # Not a pass. An assembly that will not realize returns None below
            # and is the 'cad' test's business; reaching here instead means the
            # check itself broke, and reporting that as "no interference found"
            # is how a check comes to certify what it never looked at.
            #
            # It did: json.dumps() cannot encode the BREP bytes the envelope
            # carries, the TypeError landed here, and every assembly passed
            # without being examined. The message was at debug level, so
            # nothing said so.
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the interference check could not be run: %s" % e)

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
                "%d part(s) are not valid solids and were not checked: %s" % (len(unchecked), shown),
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

        expected = await _expected_overlap_pairs(ctx, shape)
        reported = [o for o in overlaps if not _is_expected(o, expected)]
        if not reported:
            return self.passed(shape)

        for overlap in reported:
            self.failed(
                shape,
                "'%s' and '%s' share %.3f mm^3" % (overlap["a"], overlap["b"], overlap["volume"]),
            )
        return self.TEST_FAILED


async def _expected_overlap_pairs(ctx, shape):
    """The pairs whose joint requires them to share space.

    Four ways a joint says so, none of them a property of the assembly: an
    interface that cuts its own thread wherever it is used, a connection that
    says this particular screw cuts one, a connection made by snapping one part
    past a feature on the other, and a connection that names the further items
    the same act of joining drives through.

    The last one is needed because a connection joins two items and a screw
    passes through more than two: it is connected to the part its head bears
    on, and cuts its thread in every part underneath that as well. Nothing
    about those further items is derivable from the connection, so 'interferes'
    names them.
    """
    pairs = set()
    try:
        children = list(shape.connected_children())
    except Exception:
        return pairs
    for child in children:
        connection = child.connection
        if not connection:
            continue
        target = connection.get("target")
        if target is None or child.name is None:
            continue

        # The further items this act of joining drives through, whatever made
        # the joint itself expected.
        for other in connection.get("interferes") or []:
            pairs.add(tuple(sorted((child.name, other))))

        how = child.how
        if how is not None and (getattr(how, "self_screw", False) or getattr(how, "snap_in", False)):
            pairs.add(tuple(sorted((child.name, target))))
            continue

        for key in ("with_interface", "to_interface"):
            if await _cuts_its_own_thread(ctx, connection.get(key)):
                pairs.add(tuple(sorted((child.name, target))))
                break
    return pairs


async def _cuts_its_own_thread(ctx, interface_spec):
    if not interface_spec:
        return False
    try:
        interface = ctx.get_interface(interface_spec)
    except Exception:
        return False
    if interface is None:
        return False
    try:
        return bool(interface.get_self_screw())
    except Exception:
        return False


def _is_expected(overlap, expected):
    """Whether this pair is one the joint between them requires."""
    for a, b in expected:
        names = (overlap["a"], overlap["b"])
        if _matches(names[0], a) and _matches(names[1], b):
            return True
        if _matches(names[0], b) and _matches(names[1], a):
            return True
    return False


def _matches(name, pattern):
    return name == pattern or name.endswith("/" + pattern)
