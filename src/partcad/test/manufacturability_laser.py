#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Can a laser cutter actually produce this part?

One question, and it is the beam's own geometry: a laser cuts along a fixed
axis and does not tilt, so every wall it makes is parallel to that axis. A part
whose faces are all either along the axis or across it is one the beam can cut;
a part with a chamfer, a taper, a dome or a fillet rolling over an edge is not,
however good the machine is, because there is no orientation of a beam that
produces a surface at an angle to itself.

What is deliberately *not* checked is the thickness, the material or whether the
part is flat. A laser will cut a 20 mm plate as readily as a 1 mm sheet given
enough power, and how much is enough is a property of the machine and the
material rather than of the design -- so it is not something PartCAD can answer
from the geometry, and a check that guessed would be refusing parts that the
shop next door cuts every day.
"""

from ..part_config_manufacturing import MACHINE_LASER
from .manufacturability_machine import ManufacturabilityMachineTest


class ManufacturabilityLaserTest(ManufacturabilityMachineTest):
    machine = MACHINE_LASER

    def __init__(self) -> None:
        super().__init__("manufacturability-laser")

    def judge(self, shape, machine, measured, judged_removed: bool = False) -> bool:
        """Every face is either a wall along the beam or a face across it."""
        if measured.get("other", 0):
            return self.report_tilted(
                shape, machine, measured, "A laser cutting along %s cannot make it" % machine.tool_axis
            )
        if not measured.get("walls", 0):
            # Nothing to cut. A solid block with no wall along the beam is
            # either not the part that was meant or a part the laser has no
            # work to do on, and both are worth a sentence.
            return self.failed(
                shape,
                "It has no wall along %s for a laser to cut",
                machine.tool_axis,
            )
        return self.passed(shape)
