#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The pendulum's bar: 300 mm long, 20 mm wide, 10 mm thick, with one end on the
# origin -- the line through that end's centre, across its width, is where it
# hangs from. Nothing else is cut into it, so its moment of inertia about that
# line is a box's, which is what the closed form in partcad.yaml is written for.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

length = 300.0
width = 20.0
thickness = 10.0

shape = cq.Workplane("XY").box(length, width, thickness, centered=(False, True, True))

show_object(shape)
