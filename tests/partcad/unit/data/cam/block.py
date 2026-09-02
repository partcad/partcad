import cadquery as cq

# Small on purpose: the end-to-end test builds this one.
shape = cq.Workplane("XY").box(10, 6, 2)
show_object(shape)  # noqa: F821
