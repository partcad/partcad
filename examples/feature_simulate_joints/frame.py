#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# What the pendulum hangs from: a 40 mm cube centred on its origin, its axle on
# the +Y face.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

size = 40.0

shape = cq.Workplane("XY").box(size, size, size)

show_object(shape)
