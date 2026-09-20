import cadquery as cq

length = 10.0

shape = cq.Workplane("XY").box(2.0, 2.0, length)
show_object(shape)
