#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A round rod 9 mm across and 300 mm long, along its Z axis from the origin up:
# the screw the nut runs down and the shaft the collar slides on. Thinner than
# the 10 mm bore of either, so that nothing is drawn sharing space with it.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

diameter = 9.0
length = 300.0

shape = cq.Workplane("XY").circle(diameter / 2.0).extrude(length)

show_object(shape)
