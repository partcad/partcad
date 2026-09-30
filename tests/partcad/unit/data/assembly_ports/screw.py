import cadquery as cq

# The geometry is never built: these tests only walk the assembly tree.
shape = cq.Workplane("XY").circle(1.5).extrude(6)
show_object(shape)  # noqa: F821
