import cadquery as cq

# The geometry is never built: these tests only read declarations.
shape = cq.Workplane("XY").box(40, 25, 1.6)
show_object(shape)  # noqa: F821
