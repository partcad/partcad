import cadquery as cq

# The geometry is never built: these tests only walk the assembly tree.
shape = cq.Workplane("XY").box(30, 30, 3)
show_object(shape)  # noqa: F821
