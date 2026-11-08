#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The plan of a living room, as it is drawn: from above, on the XY plane, in
# millimetres. Six metres by four, with a round bay window bulging out of the
# east wall and a column cut into the south one. One closed outline of lines and
# arcs, which is what walls can stand on.

import build123d as bd

with bd.BuildSketch() as plan:
    with bd.BuildLine():
        bd.Line((0, 0), (2600, 0))
        # The column, a half-round notch the room goes around.
        bd.ThreePointArc((2600, 0), (2900, 300), (3200, 0))
        bd.Line((3200, 0), (6000, 0))
        bd.Line((6000, 0), (6000, 1000))
        # The bay: a quarter of a circle each way, bulging out of the room.
        bd.ThreePointArc((6000, 1000), (7000, 2000), (6000, 3000))
        bd.Line((6000, 3000), (6000, 4000))
        bd.Line((6000, 4000), (0, 4000))
        bd.Line((0, 4000), (0, 0))
    bd.make_face()

# PartCAD hands a script 'show_object' to say what it made; run on its own, it
# has none.
if "show_object" in locals():
    show_object(plan.sketch)
