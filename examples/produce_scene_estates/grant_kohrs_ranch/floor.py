#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's floor: the blocks its rooms are in, inside their walls and a
# millimetre clear of them, 200 mm thick under the storey's level. Written by
# '../make_estate.py' from 'estate.json'; run that again rather than edit it.

from build123d import Kind, Location, Polygon, extrude, offset

DATA = {'insets': [[231.0, 231.0, 301.0, 231.0, 231.0, 231.0], [231.0], [301.0]],
 'levels': [300, 3000, 3650],
 'outlines': [[[(0, 0), (20193, 0), (20193, 6330), (0, 6330)],
               [(0, 6330), (5281, 6330), (5281, 9923), (0, 9923)],
               [(5281, 6330), (12366, 6330), (12366, 27300), (5281, 27300)],
               [(12366, 6330), (20193, 6330), (20193, 10000), (12366, 10000)],
               [(20151, 6164), (22685, 6164), (22685, 9969), (20151, 9969)],
               [(-1781, 9847), (5220, 9847), (5220, 11674), (-1781, 11674)]],
              [[(0, 0), (20193, 0), (20193, 6330), (0, 6330)]],
              [[(5281, 6330), (12366, 6330), (12366, 27300), (5281, 27300)]]],
 'slab': 200.0}

storey = 1


def floor(index):
    found = None
    level = DATA["levels"][index]
    for outline, inset in zip(DATA["outlines"][index], DATA["insets"][index]):
        face = offset(Polygon(*[tuple(p) for p in outline], align=None), amount=-inset, kind=Kind.INTERSECTION)
        slab = extrude(face.moved(Location((0, 0, level - DATA["slab"]))), amount=DATA["slab"])
        found = slab if found is None else found + slab
    return found


result = floor(int(storey) - 1)

if "show_object" in locals():
    show_object(result, name="floor-%s" % storey)  # noqa: F821
