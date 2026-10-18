#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A ring with a 10 mm bore and 30 mm outside, 10 mm tall, its bottom face on the
# origin and its axis along Z. About that axis a ring's moment of inertia over
# its mass is (r1^2 + r2^2) / 2 whatever its height, which is what the screw's
# closed form in partcad.yaml is written for. The thread is not drawn: the
# joint is what makes it a nut.

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

bore = 10.0
outside = 30.0
height = 10.0

shape = cq.Workplane("XY").circle(outside / 2.0).circle(bore / 2.0).extrude(height)

show_object(shape)
