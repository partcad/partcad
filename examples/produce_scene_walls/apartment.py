#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The plan of a small apartment, as it is drawn: from above, on the XY plane, in
# millimetres. Eight metres by five, and the three things a plan draws:
#
#   * its outline, a room, whose walls look into it;
#   * the closed spaces in it - a round column, cut out of the floor as a hole,
#     and a lift shaft, drawn as a closed loop inside the outline - whose walls
#     look out;
#   * a standalone wall between the living room and the bedroom, a line that
#     closes nothing, with a doorway left between it and the north wall. Its
#     thickness is to the left of the way it is drawn: west, in the living room.
#
# Everything standing in the room is drawn as the walls it is, from every side.

import build123d as bd

room = bd.Pos(4000, 2500) * bd.Rectangle(8000, 5000) - bd.Pos(2500, 2500) * bd.Circle(200)
shaft = bd.Polyline((600, 3400), (1800, 3400), (1800, 4400), (600, 4400), close=True)
wall = bd.Polyline((5000, 0), (5000, 3800))

# PartCAD hands a script 'show_object' to say what it made; run on its own, it
# has none. One call each: a face, and the two lines beside it.
if "show_object" in locals():
    show_object(room, name="room")  # noqa: F821
    show_object(shaft, name="shaft")  # noqa: F821
    show_object(wall, name="wall")  # noqa: F821
