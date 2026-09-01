# The likeness of a fingertip, for the assembly instruction book to draw
# wherever a step says an object is held by hand.
#
# Nothing is manufactured from this and nothing is measured off it: it is there
# so that a step showing two parts coming together also shows what is holding
# them. What it does have to get right is where it sits, and that is a
# convention every tool visual in PartCAD follows:
#
#   the working end of the tool is at the origin, and the tool extends along
#   -Z, because a port's +Z points *into* the object it belongs to.
#
# So a finger drawn at a port presses on that port's face from outside, which is
# what a finger does.

import build123d as bd

# How much of the finger is shown, in mm. A whole hand would be in the way of
# everything else in the picture; the last joint says enough.
LENGTH = 45.0
# A fingertip is about 14mm across.
RADIUS = 7.0

with bd.BuildPart() as result:
    # The pad that touches the object: a sphere whose pole is the contact point.
    with bd.Locations(bd.Location((0, 0, -RADIUS))):
        bd.Sphere(RADIUS)
    # The rest of the finger, running back out of the material.
    with bd.Locations(bd.Location((0, 0, -RADIUS - (LENGTH - RADIUS) / 2.0))):
        bd.Cylinder(RADIUS, LENGTH - RADIUS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="finger")
