import build123d as bd

# A flat sketch: the outline of a 120 x 40 mm nameplate with a hanging hole.
# There is no thickness here at all, which is why the `cam:` section of this
# object has to say how deep to cut -- a sketch cannot be "cut through".
with bd.BuildSketch() as result:
    bd.Rectangle(120, 40)
    bd.fillet(result.vertices(), radius=6)
    with bd.Locations((-50, 0)):
        bd.Circle(4, mode=bd.Mode.SUBTRACT)

if "show_object" in locals():
    show_object(result.sketch.wrapped, name="nameplate")
