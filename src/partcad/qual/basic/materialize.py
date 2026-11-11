#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Is this part what its machine makes by following its instructions?

A part made by `additive`, `subtractive` or `forming` says what it is made from
and how; `pc cam` works out what the machine makes by following that (see
'Shape.materialize_async') -- a print's deposit, a cut's remainder of its stock,
a molding's shrunk cavity. A part that also has a geometry of its own -- a file
written by `pc cam --materialize`, an as-printed scan, a model somebody drew --
claims to be that product, and this is where the claim is held to it.

**Only where there is a claim**: a part with no geometry of its own *is* the
product, made on demand, and there is nothing to compare. Nor is there one for a
cut part that says nothing about the cutting (no machine and no job: no machine
makes anything of it), or that is routed along its own geometry -- no
`instructions:` -- since that geometry is then what the machine follows, not
what it leaves. A part that could be made on several machines claims to be what
each of them makes, and is held to each, as the `cam` check holds it to a route
on each.

Compared by what the shapes measured as they were built -- the volume and the
bounding box each payload carries -- with no boolean between them: a print is
tens of thousands of prisms, and the question is whether the two are the same
part, which their extent and their volume answer to within the part's own
tolerance. The volume may differ by the tolerance over the box's surface; every
side of the box by the tolerance. A print is also allowed to be its outside:
a part modelled solid that is printed with infill matches the print's sections
stacked up (the route's `solid_volume`), which is what it looks like and weighs
nothing like.
"""

from ... import shape_envelope
from ...part import Part
from ...part_config import PartConfiguration
from ...part_config_manufacturing import (
    MANUFACTURED_TYPE,
    MATERIALIZED_METHODS,
    METHOD_SUBTRACTIVE,
    ROUTED_MACHINES,
    says_how_it_is_cut,
)
from ..qualification import BasicQualification, Qualification

# What the part is compared at when it states no tolerance, in mm.
DEFAULT_TOLERANCE = 0.1


def _measured(envelope):
    """(volume, bbox) a payload recorded as it was built, or (None, None)."""
    if not isinstance(envelope, dict):
        return None, None
    metadata = envelope.get(shape_envelope.KEY_METADATA)
    measurements = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS) or {}
    return measurements.get(shape_envelope.METADATA_VOLUME), measurements.get(shape_envelope.METADATA_BBOX)


def _box_surface(bbox) -> float:
    dx, dy, dz = (bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
    return 2.0 * (dx * dy + dy * dz + dz * dx)


def _compared(shape):
    """The machines a part's geometry is held to the product of, and why none where it is held to none.

    '[None]' for a part made one way; each machine's name where it names
    several, since each is a claim. A cut part is held only where its product is
    made from something other than the part itself: none where it says nothing
    about the cutting, and not a machine that is routed along the part's own
    geometry (no 'instructions:'). That geometry is the design the router, the
    laser or the drill follows rather than a claim about what it leaves: a
    pocket's product is the stock with the part taken out of it, and a profile's
    differs from it by whatever a 2.5-axis route cannot cut, which the route
    warns about as it is made ('the outline changes over the depth of the cut').
    """
    data = PartConfiguration.get_manufacturing_data(shape)
    choices = data.machine_choices()
    machines = list(choices) if len(choices) > 1 else [None]
    if data.method != METHOD_SUBTRACTIVE or data.machine_error:
        # A section that cannot be read is held to its product all the same, so
        # that the run says what is wrong with it.
        return machines, None
    if not says_how_it_is_cut(data):
        return [], (
            "it says nothing about how it is cut (no machine and no job under 'manufacturing:'), so no machine"
            " makes anything to compare it with"
        )
    if data.instructions:
        return machines, None
    held = []
    for machine in machines:
        chosen = data.machine_named(machine) if machine is not None else data.machine
        # No machine but a job is a router's job ('cam.declared_config').
        if chosen is None or chosen.kind in ROUTED_MACHINES:
            continue
        held.append(machine)
    if not held:
        return [], (
            "it is cut along its own geometry (no 'instructions:'), which is then what its machine follows rather"
            " than a claim about what the machine leaves of its stock"
        )
    return held, None


def _mismatch(own, made, tolerance):
    """Why the part's geometry is not the product, as a sentence; None where it is."""
    own_volume, own_box = _measured(own)
    made_volume, made_box = _measured(made.get("product"))
    if own_volume is None or own_box is None or made_volume is None or made_box is None:
        return "The part or what its machine makes recorded no measurements to compare"

    off = [abs(a - b) for a, b in zip(own_box, made_box)]
    if max(off) > tolerance + 1e-6:
        return (
            "It is not the size its machine makes it: its extent differs by %.3f mm, beyond its %.3f mm tolerance "
            "(run 'pc cam --materialize' to write what the machine makes)" % (max(off), tolerance)
        )

    allowed = tolerance * _box_surface(own_box) + 1e-6
    candidates = [made_volume]
    solid = (made.get("stats") or {}).get("solid_volume")
    if solid:
        candidates.append(float(solid))
    closest = min(candidates, key=lambda volume: abs(volume - own_volume))
    if abs(closest - own_volume) > allowed:
        return (
            "It is not what its machine makes: it is %.1f mm3 and the machine makes %.1f mm3, more than its "
            "tolerance allows (%.1f mm3); run 'pc cam --materialize' to write what the machine makes"
            % (own_volume, made_volume, allowed)
        )
    return None


class MaterializeTest(BasicQualification):
    WRAPPERS = ("manufacturability.py",)

    def __init__(self) -> None:
        super().__init__("materialize")

    def inapplicable(self, shape):
        if not isinstance(shape, Part):
            return "only a part is made by a manufacturing method"
        data = PartConfiguration.get_manufacturing_data(shape)
        if data._method_string() not in MATERIALIZED_METHODS:
            return "it is not made by following instructions ('additive', 'subtractive' or 'forming')"
        if not data.source:
            return "it names nothing it is made from ('manufacturing: source:')"
        if isinstance(shape.config, dict) and shape.config.get("type") == MANUFACTURED_TYPE:
            return "it has no geometry of its own: it is what its machine makes, so there is nothing to compare"
        _machines, reason = _compared(shape)
        return reason

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What the product is made from and how, which the part's own key leaves out."""
        if self.inapplicable(shape) is not None:
            return ""
        from ...part_factory_manufactured import product_key_async

        # None where something it is made from keeps no key: 'test' then says
        # its verdict is not to be kept, so nothing is ever read back from here.
        return ".materialize=" + (await product_key_async(ctx, shape) or "unkept")

    async def test(self, tests_to_run: list[Qualification], ctx, shape, test_ctx: dict = {}) -> bool:
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)
        from ...part_factory_manufactured import product_key_async

        if await product_key_async(ctx, shape) is None:
            # Made from something that keeps no key ('cache: false'): an edit of
            # it would leave the key as it is, so the verdict must not be kept.
            test_ctx[self.NOT_CACHEABLE] = True

        own = await shape.get_wrapped(ctx)
        if own is None:
            return self.failed(shape, "Failed to get the shape")
        tolerance = await shape.get_tolerance()
        tolerance = float(tolerance) if tolerance else DEFAULT_TOLERANCE

        machines, _reason = _compared(shape)
        for machine in machines:
            on = "" if machine is None else "On its '%s': " % machine
            try:
                made = await shape.materialize_async(ctx, machine=machine)
            except Exception as e:  # pylint: disable=broad-except
                return self.failed(shape, "%sWhat its machine makes could not be worked out: %s", on, e)
            mismatch = _mismatch(own, made, tolerance)
            if mismatch is not None:
                return self.failed(shape, "%s%s", on, mismatch)
        return self.passed(shape)
