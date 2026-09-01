import cadquery as cq

# The geometry is never built: these tests only ask which tool acts where, not
# what it looks like. It follows the convention every tool visual follows all
# the same - the working end at the origin, the body along -Z.
shape = cq.Workplane("XY").circle(3).extrude(-30)
show_object(shape)  # noqa: F821
