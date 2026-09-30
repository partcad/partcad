import cadquery as cq

# The geometry is never built: these tests only walk the ports and interfaces.
thickness = 3.0
shape = cq.Workplane("XY").box(40, 40, thickness)
show_object(shape)  # noqa: F821
