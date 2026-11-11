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
product, made on demand, and there is nothing to compare.

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

import hashlib

from ... import shape_envelope
from ...part import Part
from ...part_config import PartConfiguration
from ...part_config_manufacturing import MANUFACTURED_TYPE, MATERIALIZED_METHODS
from ..qualification import BasicQualification, Qualification
from .manufacturability_reference import reference_key

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
        return None

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What the product is made from and how, which the part's own key leaves out."""
        if self.inapplicable(shape) is not None:
            return ""
        data = PartConfiguration.get_manufacturing_data(shape)
        declared = [await reference_key(ctx, shape, data.source, "part")]
        if data.instructions:
            declared.append(await reference_key(ctx, shape, data.instructions, "part"))
        declared += [data.machines[kind].key() for kind in data.machine_choices()]
        declared.append("error:%s" % (data.machine_error or ""))
        return ".materialize=" + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def test(self, tests_to_run: list[Qualification], ctx, shape, test_ctx: dict = {}) -> bool:
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)

        own = await shape.get_wrapped(ctx)
        if own is None:
            return self.failed(shape, "Failed to get the shape")
        try:
            made = await shape.materialize_async(ctx)
        except Exception as e:  # pylint: disable=broad-except
            return self.failed(shape, "What its machine makes could not be worked out: %s", e)

        own_volume, own_box = _measured(own)
        made_volume, made_box = _measured(made.get("product"))
        if own_volume is None or own_box is None or made_volume is None or made_box is None:
            return self.failed(shape, "The part or what its machine makes recorded no measurements to compare")

        tolerance = await shape.get_tolerance()
        tolerance = float(tolerance) if tolerance else DEFAULT_TOLERANCE

        off = [abs(a - b) for a, b in zip(own_box, made_box)]
        if max(off) > tolerance + 1e-6:
            return self.failed(
                shape,
                "It is not the size its machine makes it: its extent differs by %.3f mm, beyond its %.3f mm tolerance "
                "(run 'pc cam --materialize' to write what the machine makes)",
                max(off),
                tolerance,
            )

        allowed = tolerance * _box_surface(own_box) + 1e-6
        candidates = [made_volume]
        solid = (made.get("stats") or {}).get("solid_volume")
        if solid:
            candidates.append(float(solid))
        closest = min(candidates, key=lambda volume: abs(volume - own_volume))
        if abs(closest - own_volume) > allowed:
            return self.failed(
                shape,
                "It is not what its machine makes: it is %.1f mm3 and the machine makes %.1f mm3, more than its "
                "tolerance allows (%.1f mm3); run 'pc cam --materialize' to write what the machine makes",
                own_volume,
                made_volume,
                allowed,
            )
        return self.passed(shape)
