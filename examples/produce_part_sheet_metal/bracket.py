# The blank folded at both bend lines: up at the first, down at the second, so
# the strip comes out as a Z.
#
# Modelled from the very numbers the drawing states - where each bend line is,
# and the angle and inner radius written against it - because that is the
# relationship the declaration describes. PartCAD does not bend the blank itself
# yet, so this script is where the two are kept in step.
#
# A piece of sheet is a cross-section carried along a line, so that is how it is
# built: the centreline of the bent profile, filleted where it turns, with the
# section of the strip swept along it. The part comes out with exactly the
# volume of the blank, because that is what bending does to a piece of metal.

from math import radians, tan

import build123d as bd

THICKNESS = 2.0  # the sheet the blank is cut from
INNER_RADIUS = 2.0  # what 'radius' says against each bend line
BEND_ANGLE = 90.0  # ...and what 'angle' says
WIDTH = 40.0  # across the blank
FLAT = (30.0, 50.0, 40.0)  # edge to BEND_UP, BEND_UP to BEND_DOWN, and on to the edge

# The neutral axis sits at mid-thickness, so the flat length a bend takes up is
# its arc there, while a sharp corner would take up the two tangent lengths
# instead. Sharing that difference between the segments either side is what
# turns the flat pattern's dimensions into the sharp-cornered centreline below -
# and is why that centreline comes back out 120mm long, which is the blank.
NEUTRAL = INNER_RADIUS + THICKNESS / 2
SETBACK = NEUTRAL * tan(radians(BEND_ANGLE) / 2) - NEUTRAL * radians(BEND_ANGLE) / 2
LOWER, WEB, UPPER = FLAT[0] + SETBACK, FLAT[1] + 2 * SETBACK, FLAT[2] + SETBACK

with bd.BuildPart() as result:
    with bd.BuildLine(bd.Plane.XZ) as centreline:
        # Along, up at the first bend line, along again at the second: the two
        # turns are in opposite senses, which is what 'up' and then 'down' means
        # and what makes this a Z rather than a channel.
        bd.Polyline((0, 0), (LOWER, 0), (LOWER, WEB), (LOWER + UPPER, WEB))
        # The two corners of the Z, and only those: the ends of the strip are
        # where the metal stops, not where it turns.
        bd.fillet(centreline.vertices().sort_by(bd.Axis.X)[1:-1], radius=NEUTRAL)
    with bd.BuildSketch(bd.Plane.YZ):
        bd.Rectangle(WIDTH, THICKNESS)
    bd.sweep()

if "show_object" in locals():
    show_object(result.part.wrapped, name="bracket")
