# What a router does that the other two machines cannot.
#
# A pocket with a flat floor partway down, and a chamfer around the top edge:
# neither is something a laser or a drill can produce. The chamfer is the clear
# case - it is a wall at 45 degrees to the tool axis, and there is no
# orientation of a beam that cuts one - which is exactly why this part declares
# `cnc:` and the gasket beside it declares `laser:`.

import build123d as bd

LENGTH = 100.0
WIDTH = 60.0
THICKNESS = 12.0
POCKET = (70.0, 34.0)
POCKET_DEPTH = 6.0
BORE = 16.0
CHAMFER = 1.5

with bd.BuildPart() as result:
    bd.Box(LENGTH, WIDTH, THICKNESS)
    # The pocket, cut down from the top face and stopping short of the bottom.
    with bd.BuildSketch(bd.Plane.XY.offset(THICKNESS / 2)) as pocket:
        bd.Rectangle(*POCKET)
        bd.fillet(pocket.vertices(), radius=6.0)
    bd.extrude(amount=-POCKET_DEPTH, mode=bd.Mode.SUBTRACT)
    # A bore all the way through, at the centre of the pocket floor.
    with bd.BuildSketch(bd.Plane.XY):
        bd.Circle(BORE / 2)
    bd.extrude(amount=THICKNESS, both=True, mode=bd.Mode.SUBTRACT)
    # And the chamfer, which is the whole point of the part.
    bd.chamfer(result.faces().sort_by(bd.Axis.Z)[-1].edges().filter_by(bd.GeomType.LINE), length=CHAMFER)

if "show_object" in locals():
    show_object(result.part.wrapped, name="bearing_block")
