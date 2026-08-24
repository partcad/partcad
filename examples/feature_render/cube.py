#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

shape = cq.Workplane("front").box(20.0, 20.0, 20.0)

show_object(shape)
