import cadquery as cq

# The geometry is never built: these tests only read the assembly tree.
shape = cq.Workplane("XY").box(1, 1, 1)
show_object(shape)  # noqa: F821
