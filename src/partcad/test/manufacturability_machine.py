#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a particular subtractive machine can and cannot make.

`manufacturability-subtractive` asks whether a part could be cut out of its
stock at all. This asks the narrower question the machine raises: a router will
follow any 2.5D path, but a laser's beam does not tilt and a drill only goes in
and out, so each of those two can produce some of what the first can and no
more.

The common half of that is one measurement -- how each face of the part lies
relative to the axis the machine works along -- and it is made once, in
`wrappers/wrapper_manufacturability.cut_directions`. What differs between the
machines is what they demand of the answer, which is what the two subclasses
below supply.

The checks apply **only to a part that named the machine**. A `subtractive` part
that names none is a CNC part, and CNC is the machine that can make anything the
other two can, so there is nothing for these to say about it -- and saying
anything would mean a package that has declared `method: subtractive` for a year
suddenly failing a check about a laser it does not own.
"""

import hashlib

from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_SUBTRACTIVE
from .manufacturability_reference import resolve_reference
from .test import Test


class ManufacturabilityMachineTest(Test):
    """One subtractive machine's own limits, asked of the parts that name it.

    Subclasses set `machine` to the kind they are about and implement
    `judge()`, which is handed what `cut_directions` measured.
    """

    # Which machine this check is about, as a part's 'manufacturing:' section
    # names it. Set by the subclass.
    machine: str = ""

    # Whether this machine is judged on what it *removed* rather than on the
    # part it left behind. They are different questions, and which one is right
    # depends on how much of the part the machine is responsible for: a laser
    # cuts the outline, so the part's own walls are its work, while a drill is
    # only responsible for the holes and a plate's straight sides came with the
    # stock. Needs a 'source:', and falls back to the part where there is none.
    judges_removed: bool = False

    async def cache_key_suffix(self, ctx, shape) -> str:
        """The machine and the axis, neither of which moves the part's hash.

        Turning the part over -- the same solid, cut from the other side -- is
        the whole of what `direction:` says, and it changes the answer: the
        walls that were parallel to the axis are now across it. So the axis is
        in the key, and a part whose direction is corrected re-runs rather than
        being handed the verdict on the direction it replaced.
        """
        machine = self._machine_of(shape)
        if machine is None:
            return ""
        declared = "%s:%s" % (machine.kind, machine.direction)
        return ".%s=" % self.machine + hashlib.sha256(declared.encode()).hexdigest()[:16]

    def _machine_of(self, shape):
        """The machine this part named, where it is the one this check is about.

        None for everything else, which is the ordinary case: a sketch, an
        assembly, a part made some other way, a subtractive part on a different
        machine, and -- deliberately -- a subtractive part that named no machine
        at all. See the module docstring for why the default CNC does not count
        as having named one.
        """
        if not isinstance(shape, Part):
            return None
        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_SUBTRACTIVE:
            return None
        machine = manufacturing_data.machine
        if machine is None or not machine.declared or machine.kind != self.machine:
            return None
        return machine

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        machine = self._machine_of(shape)
        if machine is None:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")

        source_envelope = None
        if self.judges_removed:
            manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
            if manufacturing_data.source:
                source = await resolve_reference(ctx, shape, manufacturing_data.source, "part")
                if source is None:
                    # Reported by 'manufacturability-subtractive', which is the
                    # check the 'source:' belongs to. Saying it twice would put
                    # two lines against one mistake, so this one measures what
                    # it can -- the part itself -- and leaves the missing stock
                    # to the check that is about it.
                    self.debug(shape, "The source part '%s' is not found", manufacturing_data.source)
                else:
                    source_envelope = await source.get_wrapped(ctx)

        from .manufacturability_analysis import cut_directions

        measured = await cut_directions(ctx, envelope, machine.vector, source_envelope)
        return self.judge(shape, machine, measured, judged_removed=source_envelope is not None)

    def judge(self, shape, machine, measured, judged_removed: bool = False) -> bool:
        """The verdict this machine reaches on what was measured.

        'judged_removed' says which subject the numbers describe: the material
        the machine took off, or the part it left behind. A verdict has to know,
        because the sentence it writes about a failure names one or the other.
        """
        raise NotImplementedError

    def report_tilted(self, shape, machine, measured, what: str) -> bool:
        """The failure both machines share: a wall that is not along the axis.

        Named with what the worst offender is and how far off it is, because
        "3 faces are not vertical" sends the reader to look at the whole part
        while "a Cone tilted 56.3 degrees" sends them to the feature.
        """
        offenders = measured.get("offenders") or []
        detail = ""
        if offenders:
            worst = max(offenders, key=lambda one: one.get("tilt") or 0.0)
            detail = " (the worst is a %s tilted %.1f degrees off it)" % (
                worst.get("surface", "face"),
                worst.get("tilt") or 0.0,
            )
        return self.failed(
            shape,
            "%s: %d of its faces are neither along %s nor across it%s",
            what,
            measured.get("other", 0),
            machine.direction,
            detail,
        )
