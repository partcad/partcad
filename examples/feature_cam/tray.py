import build123d as bd

# The *void* of a tray, not the tray: a 160 x 100 x 8 mm block standing for the
# material a pocket removes. An `operation: pocket` clears what is inside the
# outline it is given, so what the object describes is the hole that is left
# rather than the thing that is left around it.
#
# No hole in it, and that is a constraint rather than an oversight: an island in
# the middle of a pocket is material the route would have to leave, and the
# built-in implementation refuses one rather than cutting through it.
with bd.BuildPart() as result:
    with bd.BuildSketch() as outline:
        bd.Rectangle(160, 100)
        bd.fillet(outline.vertices(), radius=12)
    bd.extrude(amount=8)

if "show_object" in locals():
    show_object(result.part.wrapped, name="tray_recess")
