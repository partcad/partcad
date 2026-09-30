import cadquery as cq

result = cq.Workplane("XY").box(1, 1, 1)
show_object(result)
