#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Is this part what a saw leaves of its stock?

A cut is the most limited subtractive machine there is and the most common one:
a board cut to length, a sheet cut to size. It follows no outline and makes no
feature. It goes straight through the stock along a plane, and everything on
the far side of that plane is the offcut. So a part made that way is not merely
one that fits inside its stock -- `manufacturability-subtractive` asks that --
it is exactly the stock with the declared cuts taken off, and nothing else.

That is the one question, and it is asked by building the answer: the stock is
cut at each declared plane in turn, and the result is compared with the part.
Whatever the part has that the cut stock does not is a feature no saw made;
whatever the cut stock has that the part does not is a notch, a hole or a cut
in the wrong place. Either is a declaration that does not describe how the part
is made.

A cut that takes nothing off is reported too. It is a plane that misses the
stock -- usually a length longer than the board, or a normal pointing the wrong
way -- and a list of cuts with one that does nothing in it is not the list
somebody meant to write.

Applies only to a part that names `cut:`, like the laser and drill checks, and
for the same reason.
"""

import hashlib

from ..part_config import PartConfiguration
from ..part_config_manufacturing import MACHINE_CUT
from .manufacturability_machine import ManufacturabilityMachineTest
from .manufacturability_reference import reference_key, resolve_reference

# How much the part and the cut stock may differ and still be the same solid,
# as a fraction of the part's volume. The same allowance, for the same reason,
# as 'manufacturability_subtractive.OUTSIDE_FRACTION': two independently built
# solids that meet face to face leave slivers of the order of the modelling
# tolerance, and a cut in the wrong place misses by far more.
DIFFERENCE_FRACTION = 1e-6


class ManufacturabilityCutTest(ManufacturabilityMachineTest):
    machine = MACHINE_CUT
    judges_removed = True

    def __init__(self) -> None:
        """Registered under the name '-f manufacturability-cut' selects."""
        super().__init__("manufacturability-cut")

    async def cache_key_suffix(self, ctx, shape) -> str:
        """The cuts, and the stock they are made in.

        Both are read out of `manufacturing:`, which a shape's hash leaves out,
        and the stock is another object whose own hash is what says it changed.
        A cut moved by an inch has to re-run, and so does a board that got
        longer.
        """
        machine = self._machine_of(shape)
        if machine is None:
            return ""
        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        declared = [
            "%s:%s" % (machine.kind, machine.key()),
            "source:" + await reference_key(ctx, shape, manufacturing_data.source, "part"),
        ]
        return ".%s=" % self.machine + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def test(self, tests_to_run, ctx, shape, test_ctx: dict = {}) -> bool:
        """Cut the stock where the part says, and compare what is left with it."""
        machine = self._machine_of(shape)
        if machine is None:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if not manufacturing_data.source:
            # 'manufacturability-subtractive' says so, and saying it twice puts
            # two lines against one mistake.
            self.debug(shape, "No stock to cut")
            return self.TEST_PASSED
        source = await resolve_reference(ctx, shape, manufacturing_data.source, "part")
        if source is None:
            self.debug(shape, "The source part '%s' is not found", manufacturing_data.source)
            return self.TEST_PASSED

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")
        source_envelope = await source.get_wrapped(ctx)
        if source_envelope is None:
            return self.failed(shape, "Failed to get the shape of the stock '%s'", manufacturing_data.source)

        from .manufacturability_analysis import cut

        measured = await cut(ctx, envelope, source_envelope, machine.cuts)
        return self.judge_cut(shape, manufacturing_data.source, measured)

    def judge_cut(self, shape, reference: str, measured: dict) -> bool:
        """The verdict on what cutting the stock left, against the part."""
        # One allowance for every comparison here: the volumes are OCCT's
        # floating point, so a plane that misses the stock leaves a sliver of
        # the order of the modelling tolerance rather than an exact zero.
        part_volume = measured.get("part_volume") or 0.0
        allowance = max(part_volume, 1.0) * DIFFERENCE_FRACTION
        for index, removed in enumerate(measured.get("removed") or []):
            if removed <= allowance:
                plane = (measured.get("planes") or [{}])[index]
                return self.failed(
                    shape,
                    "Cut #%d (%s) takes nothing off the stock '%s'",
                    index + 1,
                    _describe(plane),
                    reference,
                )

        extra = measured.get("extra_volume") or 0.0
        missing = measured.get("missing_volume") or 0.0
        if extra > allowance or missing > allowance:
            reasons = []
            if extra > allowance:
                reasons.append("%.3f mm3 of the part is not in what the cuts leave" % extra)
            if missing > allowance:
                reasons.append("%.3f mm3 of what the cuts leave is not in the part" % missing)
            return self.failed(
                shape,
                "Cutting the stock '%s' at %s does not make it: %s",
                reference,
                "; ".join(_describe(plane) for plane in measured.get("planes") or []) or "no plane",
                ", and ".join(reasons),
            )
        return self.passed(shape)


def _describe(plane: dict) -> str:
    """One resolved plane, the way a failure names it."""

    def numbers(values) -> str:
        return "[%s]" % ", ".join("%g" % round(float(value), 3) for value in values or [])

    return "the plane through %s facing %s" % (numbers(plane.get("origin")), numbers(plane.get("normal")))
