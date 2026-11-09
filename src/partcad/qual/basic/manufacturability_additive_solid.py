#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#
"""Is this part one that could be printed?

`additive` is the method that builds a part up, layer by layer, out of nothing
but its material. What goes into the printer is a *design* -- the solid the
designer had in mind -- and what comes out is that design as the process makes
it: a skin a few lines thick, the inside filled at the density the print says.
So a printed part may name the two apart:

    manufacturing:
      method: additive
      source: bracket          # the design; what it is a print of
      visual: bracket-render   # optional: what it is drawn as instead
      fff:                     # the process, and how it fills the design
        walls: 3
        infill: 20%

and this is where the declaration is held to what it says:

* It can be read: the process subsection takes only that process' settings, and
  each of them is a value of its kind (see 'part_config_manufacturing').
* `visual:` is said only by a part that has no geometry of its own. One with a
  `type:` is drawn as what it is, and a second answer would be one too many.
* The design exists and is a closed solid: a body with no open edges, which is
  what a slicer needs to know what is inside it. The design rather than the part,
  because the design is what is printed -- a visual may well be a mesh nobody
  would hand to a slicer. A part that names no design is its own, and is asked
  what this check always asked of it.
"""

import hashlib

from ...part import Part
from ...part_config import PartConfiguration
from ...part_config_manufacturing import IMPLIED_TYPE_KEY, METHOD_ADDITIVE
from ..qualification import BasicQualification, Qualification
from .manufacturability_reference import reference_key, resolve_reference


def visual_conflict(part) -> str | None:
    """Why a part's own `visual:` cannot be honoured, or None where it can.

    Read off the part's own declaration rather than the configuration it
    resolves to, because the question is what *this* part wrote: a reference
    resolves to its source's configuration, and whether it was given a type by
    PartCAD or by its author is said only on its own (see
    'part_config_manufacturing.implied_type').
    """
    config = getattr(part, "config", None)
    if not isinstance(config, dict):
        return None
    section = config.get("manufacturing")
    if not isinstance(section, dict) or not section.get("visual"):
        return None
    if config.get(IMPLIED_TYPE_KEY):
        return None
    return (
        "'visual:' says what a printed part with no geometry of its own is drawn as, and this one has"
        " 'type: %s'; leave one of them out" % config.get("type")
    )


class ManufacturabilityAdditiveSolidTest(BasicQualification):
    WRAPPERS = ("manufacturability.py",)

    def __init__(self) -> None:
        super().__init__("manufacturability-additive")

    def inapplicable(self, shape):
        if not isinstance(shape, Part):
            return "only a part is made by a manufacturing method"
        if PartConfiguration.get_manufacturing_data(shape).method != METHOD_ADDITIVE:
            return "it is not made by the 'additive' method ('manufacturing: method')"
        return None

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the part itself, folded into the cache key.

        The design, which may be another object entirely: its own hash is what
        says whether the answer still holds, and `manufacturing:` is one of the
        keys a part's hash leaves out. And the declaration's own claims, so that
        correcting a process subsection re-runs the test rather than keeping the
        verdict the typo earned. A part that is its own design and says nothing
        else keys as it always did.
        """
        if not isinstance(shape, Part):
            return ""
        data = PartConfiguration.get_manufacturing_data(shape)
        if data.method != METHOD_ADDITIVE:
            return ""
        conflict = visual_conflict(shape)
        if (
            not data.design
            and not data.processes
            and not data.process_error
            and not data.machine_error
            and not conflict
        ):
            return ""
        declared = [
            await reference_key(ctx, shape, data.design, "part") if data.design else "design@self",
            "processes:" + ";".join(data.processes[kind].key() for kind in sorted(data.processes)),
            "error:%s|%s|%s" % (data.machine_error or "", data.process_error or "", conflict or ""),
        ]
        return ".additive=" + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def test(self, tests_to_run: list[Qualification], ctx, shape, test_ctx: dict = {}) -> bool:
        """What the declaration cannot say, then what it says, then the design's geometry.

        In that order, so that nothing is built for a declaration that was never
        going to be printed as written.
        """
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)

        data = PartConfiguration.get_manufacturing_data(shape)
        for error in (data.machine_error, data.process_error, visual_conflict(shape)):
            if error:
                # Reported here rather than raised while the package loads: a
                # part whose declaration is wrong is still a part, and
                # everything that is not about making it goes on working.
                return self.failed(shape, "The additive declaration says %s", error)

        # The manufacturability analysis runs in a sandbox (see
        # manufacturability_analysis), so this module needs no CAD library.
        from .manufacturability_analysis import free_bounds_count

        if not data.design:
            envelope = await shape.get_wrapped(ctx)
            if envelope is None:
                return self.failed(shape, "Failed to get the shape")
            if await free_bounds_count(ctx, envelope) != 0:
                return self.failed(shape, "The shape is not solid")
            return self.passed(shape)

        design = await resolve_reference(ctx, shape, data.design, "part")
        if design is None:
            return self.failed(shape, "The design '%s' it is printed from is not found", data.design)
        envelope = await design.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape of the design '%s'", data.design)
        if await free_bounds_count(ctx, envelope) != 0:
            return self.failed(shape, "The design '%s' is not solid", data.design)
        return self.passed(shape)
