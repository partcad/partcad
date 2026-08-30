import cadquery as cq

shape = cq.Workplane("XY").box(40, 25, 1.6)
show_object(shape)  # noqa: F821
