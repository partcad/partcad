#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A 20 mm cube, centred on the origin -- which is what `box()` produces and
# what the two assemblies beside it are written against: each states where the
# *centre* of a block goes, and the `offset:` of a `simulate:` then lifts the
# whole stack so that the bottom face sits on the floor of the scene.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

size = 20.0

shape = cq.Workplane("front").box(size, size, size)

show_object(shape)
