#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A collar with an arm: a 20 x 50 x 20 mm block with a 10 mm bore through it
# along Z, 10 mm in from one end, the bore's axis on the origin and the arm
# reaching out along +Y. It turns and slides on a shaft through the bore, and
# its centre of mass, off the shaft, is what makes it swing. The bore is cut
# out of a plain block, so the moment of inertia about the shaft is the block's
# less the bore's, which is what the closed form in partcad.yaml is written for.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

thickness = 20.0  # along X
length = 50.0  # along Y, the arm
width = 20.0  # along Z, the shaft
inset = 10.0  # from the end of the arm to the bore's axis
bore = 10.0

block = cq.Workplane("XY").box(thickness, length, width, centered=(True, False, False)).translate((0, -inset, 0))
hole = cq.Workplane("XY").circle(bore / 2.0).extrude(width)
shape = block.cut(hole)

show_object(shape)
