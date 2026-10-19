#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A 200 x 200 x 10 mm plate, centred on its origin and flat in its X-Z plane:
# what the universal joint, the ball, the planar joint, the composite and the
# loose block's base are tried with. Nothing is cut into it, so its moments of
# inertia are a box's, which is what the closed forms in partcad.yaml are
# written for.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

width = 200.0
height = 200.0
thickness = 10.0

shape = cq.Workplane("XY").box(width, thickness, height)

show_object(shape)
