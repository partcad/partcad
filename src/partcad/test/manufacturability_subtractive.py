#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#
"""Is this part one that could be cut out of the stock it names?

`subtractive` is the method that takes material away: a router, a laser, a saw,
a drill. What it says about a part is not a property of the part's own shape --
almost any solid can be machined out of a big enough block -- but a relation
between the part and what it is made *from*. So the part may name that stock,
and this is where the relation is checked.

Two questions, and the second only where the part answers the first:

* The part is a solid, the way every manufactured part has to be. That is the
  check as it has always been.
* Where the part declares a `source:`, the stock strictly contains it: nothing
  of the part outside the stock, and the stock bigger than the part somewhere.
  Cutting can only ever remove material, so a part that is not a subset of its
  stock cannot be made from it however good the machine is.

`source:` is optional here, unlike on `sheet_metal`, and deliberately: a part
cut from stock is completely described by its own geometry, so `method:
subtractive` on its own has always been a legitimate and complete declaration
and is what most parts that carry it say today. Naming the stock adds a claim,
and a claim is what there is to check.
"""

import hashlib

from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_SUBTRACTIVE
from .manufacturability_reference import reference_key, resolve_reference
from .test import Test

# How much of the part may lie outside its stock and still count as inside it,
# as a fraction of the part's own volume.
#
# Not zero, because the question is asked of two independently built solids and
# answered by a boolean: a part modelled to exactly the stock's outline meets it
# face to face, and what comes back from the cut is a sliver of the order of the
# modelling tolerance rather than an empty shape. A part that genuinely does not
# fit misses by a feature -- a boss, a flange, a hole in the wrong place -- and
# that is many orders of magnitude larger than this.
OUTSIDE_FRACTION = 1e-6


class ManufacturabilitySubtractiveTest(Test):
    def __init__(self) -> None:
        super().__init__("manufacturability-subtractive")

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the part itself, folded into the cache key.

        The stock, which is another object entirely: its own hash is what says
        whether the answer still holds, and the part's hash does not move when
        the stock is made smaller. `manufacturing:` is one of the keys a shape's
        hash deliberately leaves out, so without this a part would keep the
        verdict it earned against a blank that has since changed.

        The machine as well. It decides which of the sibling checks apply, and
        a declaration that was rejected for naming two machines has to stop
        being rejected the moment one of them is deleted.
        """
        if not isinstance(shape, Part):
            return ""
        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_SUBTRACTIVE:
            return ""

        machine = manufacturing_data.machine
        declared = [
            await reference_key(ctx, shape, manufacturing_data.source, "part"),
            "machine:%s" % (machine.kind if machine else manufacturing_data.machine_error or ""),
            "direction:%s" % (machine.direction if machine else ""),
        ]
        return ".subtractive=" + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Part):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_SUBTRACTIVE:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        if manufacturing_data.machine_error:
            # Reported here rather than raised while the package loads: a part
            # whose machine subsection is wrong is still a part, and everything
            # that is not about making it goes on working.
            return self.failed(shape, "The subtractive declaration says %s", manufacturing_data.machine_error)

        # The manufacturability analysis runs in a sandbox (see
        # manufacturability_analysis), so this module needs no CAD library.
        from .manufacturability_analysis import free_bounds_count

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")
        if await free_bounds_count(ctx, envelope) != 0:
            return self.failed(shape, "The shape is not solid")

        if not manufacturing_data.source:
            # Nothing was claimed beyond the method, so there is nothing further
            # to check. Not a skip: the question this check asks of every
            # subtractive part was asked and answered above.
            return self.passed(shape)

        return await self.fits_the_stock(ctx, shape, envelope, manufacturing_data.source)

    async def fits_the_stock(self, ctx, shape, envelope, reference: str) -> bool:
        """Whether the part is what is left of the stock it names.

        Both halves of "strictly bigger" are asked, because each catches a
        different mistake and neither implies the other. A part that pokes out
        of its stock cannot be cut from it at all; a part that fills its stock
        exactly is one whose `source:` names itself, or a copy of itself, which
        is the mistake a reader of the YAML cannot see.
        """
        source = await resolve_reference(ctx, shape, reference, "part")
        if source is None:
            return self.failed(shape, "The subtractive source part '%s' is not found", reference)

        source_envelope = await source.get_wrapped(ctx)
        if source_envelope is None:
            return self.failed(shape, "Failed to get the shape of the subtractive source part '%s'", reference)

        from .manufacturability_analysis import enclosure

        measured = await enclosure(ctx, envelope, source_envelope)
        part_volume = measured.get("part_volume") or 0.0
        outside = measured.get("outside_volume") or 0.0
        removed = measured.get("removed_volume") or 0.0

        if outside > max(part_volume, 1.0) * OUTSIDE_FRACTION:
            return self.failed(
                shape,
                "It does not fit the stock '%s': %.3f mm3 of it is outside, which cutting cannot produce",
                reference,
                outside,
            )
        if removed <= 0.0:
            return self.failed(
                shape,
                "The stock '%s' is the same solid as the part, so nothing is cut from it",
                reference,
            )
        return self.passed(shape)
