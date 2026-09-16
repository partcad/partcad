# The plate with nothing done to it but holes.
#
# A drill goes in and comes out, so round holes along one axis are the only
# thing it makes. The outline of this part is the outline of the stock, because
# the drill did not cut it - and that is why `source:` matters here more than
# anywhere else: it is what tells `manufacturability-drilling` to judge the
# material taken away rather than the part left behind, so the plate's straight
# sides are not counted as something a drill was supposed to produce.

import build123d as bd

LENGTH = 120.0  # the stock's own size: the drill does not touch the outline
WIDTH = 80.0
THICKNESS = 12.0
HOLE = 8.0
SPACING = (80.0, 48.0)

with bd.BuildPart() as result:
    bd.Box(LENGTH, WIDTH, THICKNESS)
    with bd.BuildSketch() as holes:
        with bd.GridLocations(SPACING[0], SPACING[1], 2, 2):
            bd.Circle(HOLE / 2)
    bd.extrude(amount=THICKNESS, both=True, mode=bd.Mode.SUBTRACT)

if "show_object" in locals():
    show_object(result.part.wrapped, name="drilled_plate")
