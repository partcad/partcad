#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Can a drilling machine actually produce this part?

A drill is the most limited of the three subtractive machines, and it is limited
in two ways rather than one. Like a laser it only works along its own axis, so
every wall it makes is parallel to that axis. Unlike a laser it cannot follow a
path at all: it goes in and comes out, so the only wall it can make is a
**round** one. A slot, a rectangular cut-out and a profiled outline are all
perfectly vertical and none of them is something a drill produces.

So both are asked, and the second is what distinguishes this from the laser
check. What the roundness is asked *of* matters: it is asked of the walls of the
part, so a part whose outline is a rectangle fails -- correctly, because a drill
did not make that rectangle. A part that is drilled *from* stock says so with
`source:`, and then the outline belongs to the stock and the drill is only
responsible for the holes; that is the declaration to write, and
`manufacturability-subtractive` is what checks it.
"""

from ..part_config_manufacturing import MACHINE_DRILL
from .manufacturability_machine import ManufacturabilityMachineTest


class ManufacturabilityDrillTest(ManufacturabilityMachineTest):
    machine = MACHINE_DRILL
    # A drill is responsible for the holes and nothing else, so it is judged on
    # what it took out rather than on the part that is left. See
    # 'ManufacturabilityMachineTest.judges_removed'.
    judges_removed = True

    def __init__(self) -> None:
        """Registered under the name '-f manufacturability-drill' selects."""
        super().__init__("manufacturability-drill")

    def judge(self, shape, machine, measured, judged_removed: bool = False) -> bool:
        """Every wall is along the axis, and every one of them is round."""
        if measured.get("other", 0):
            return self.report_tilted(
                shape, machine, measured, "A drill working along %s cannot make it" % machine.tool_axis
            )

        walls = measured.get("walls", 0)
        round_walls = measured.get("round", 0)
        subject = "what it cuts away" if judged_removed else "it"
        if not walls:
            return self.failed(shape, "There is no hole along %s for a drill to make in %s", machine.tool_axis, subject)
        if round_walls != walls:
            return self.failed(
                shape,
                "A drill only makes round holes, and %d of the %d walls along %s in %s %s not round%s",
                walls - round_walls,
                walls,
                machine.tool_axis,
                subject,
                "is" if walls - round_walls == 1 else "are",
                "" if judged_removed else " (name the stock with 'source:' so the outline is not counted as drilled)",
            )
        return self.passed(shape)
