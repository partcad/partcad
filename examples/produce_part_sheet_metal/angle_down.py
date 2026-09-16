# The blank folded at the BEND_DOWN line alone: one bend, downwards, so the
# strip comes out as an L with a long leg lying flat and a short one hanging
# down.
#
# It is 'bracket.py' with one fewer corner in it, and that is the point of the
# set: what makes each part different is which bend lines its instructions
# select out of the one drawing. See 'bracket.py' for what the arithmetic below
# is doing.

from math import radians, tan

import build123d as bd

THICKNESS = 2.0
INNER_RADIUS = 2.0
BEND_ANGLE = 90.0
WIDTH = 40.0
FLAT = (80.0, 40.0)  # edge to BEND_DOWN, and BEND_DOWN on to the far edge

NEUTRAL = INNER_RADIUS + THICKNESS / 2
SETBACK = NEUTRAL * tan(radians(BEND_ANGLE) / 2) - NEUTRAL * radians(BEND_ANGLE) / 2
FOOT, LEG = FLAT[0] + SETBACK, FLAT[1] + SETBACK

with bd.BuildPart() as result:
    with bd.BuildLine(bd.Plane.XZ) as centreline:
        # Along, then down: 'direction: down' turns the metal towards -Z.
        bd.Polyline((0, 0), (FOOT, 0), (FOOT, -LEG))
        # The bend, named by where it is. The two vertices of the turned leg
        # share an X, so sorting on that would pick between them by whatever
        # order they came out in - and one of the two is the free end of the
        # strip, which is not a bend.
        bd.fillet([centreline.vertices().sort_by_distance(bd.Vector(FOOT, 0, 0))[0]], radius=NEUTRAL)
    with bd.BuildSketch(bd.Plane.YZ):
        bd.Rectangle(WIDTH, THICKNESS)
    bd.sweep()

if "show_object" in locals():
    show_object(result.part.wrapped, name="angle_down")
