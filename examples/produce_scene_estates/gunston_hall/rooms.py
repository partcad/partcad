#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's plan, seen from above: the outlines of its rooms, which their walls
# stand on, as HABS measured them - every room of the storey, all of them on its
# level, or the one 'room' names ('2-3' is the third of the second storey).
# Written by '../make_estate.py' from 'estate.json'; run that again rather than
# edit it.

from build123d import Compound, Polygon

ROOMS = {'1-1': [[1259, 485], [6699, 485], [6699, 5191], [1259, 5191]],
 '1-2': [[1201, 7270], [6676, 7270], [6676, 12011], [1201, 12011]],
 '1-3': [[447, 5401], [6676, 5401], [6676, 7059], [447, 7059]],
 '1-4': [[7093, 485], [10910, 485], [10910, 12011], [7093, 12011]],
 '1-5': [[11351, 6277], [17336, 6277], [17336, 12011], [11351, 12011]],
 '1-6': [[11351, 485], [17383, 485], [17383, 5927], [11351, 5927]],
 '2-1': [[1019, 1766], [5359, 1766], [5359, 5235], [440, 5235], [440, 3997], [1019, 3997]],
 '2-2': [[5532, 1766], [9375, 1766], [9375, 5235], [5532, 5235]],
 '2-3': [[9525, 1766], [13403, 1766], [13403, 5235], [9525, 5235]],
 '2-4': [[13542, 1766], [17454, 1766], [17454, 5235], [13542, 5235]],
 '2-5': [[440, 7127], [6169, 7127], [6169, 10758], [961, 10758], [961, 8423], [440, 8423]],
 '2-6': [[6285, 7127], [10972, 7127], [10972, 10758], [6285, 10758]],
 '2-7': [[11099, 7127], [17454, 7127], [17454, 10758], [11099, 10758]],
 '2-8': [[440, 5433], [18032, 5433], [18032, 6928], [440, 6928]]}

storey = 1
room = ""


def outline(name):
    return Polygon(*[tuple(p) for p in ROOMS[name]], align=None)


def order(name):
    return tuple(int(n) for n in name.split("-"))


if room:
    result = outline(room)
else:
    # Side by side: an outline is its room's inside face, and walls stand
    # between rooms, so no two outlines touch.
    result = Compound([outline(name) for name in sorted(ROOMS, key=order) if order(name)[0] == int(storey)])

if "show_object" in locals():
    show_object(result, name=room or "plan-%s" % storey)  # noqa: F821
