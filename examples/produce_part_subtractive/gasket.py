# A laser part with something in it: an outline and six bolt holes, all cut in
# one pass by a beam that goes straight through the sheet.
#
# Every wall of it is parallel to the beam, which is what
# `manufacturability-laser` checks and what a laser can produce. Rounding the
# corners costs it nothing - a curve is as easy to follow as a straight line -
# while a chamfer on the top edge would be impossible, because the beam does not
# tilt.

import build123d as bd

LENGTH = 90.0
WIDTH = 60.0
THICKNESS = 2.0
CORNER = 8.0
BOLT = 5.0

with bd.BuildPart() as result:
    with bd.BuildSketch() as outline:
        bd.Rectangle(LENGTH, WIDTH)
        bd.fillet(outline.vertices(), radius=CORNER)
        with bd.Locations((0, 0)):
            bd.Circle(18.0, mode=bd.Mode.SUBTRACT)
        with bd.GridLocations(LENGTH - 16.0, WIDTH - 16.0, 2, 2):
            bd.Circle(BOLT / 2, mode=bd.Mode.SUBTRACT)
        with bd.Locations((0, (WIDTH - 16.0) / 2), (0, -(WIDTH - 16.0) / 2)):
            bd.Circle(BOLT / 2, mode=bd.Mode.SUBTRACT)
    bd.extrude(amount=THICKNESS / 2, both=True)

if "show_object" in locals():
    show_object(result.part.wrapped, name="gasket")
