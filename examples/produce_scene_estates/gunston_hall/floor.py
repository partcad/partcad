#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's floor: the blocks its rooms are in, inside their walls and a
# millimetre clear of them, 200 mm thick under the storey's level. Written by
# '../make_estate.py' from 'estate.json'; run that again rather than edit it.

from build123d import Kind, Location, Polygon, extrude, offset

DATA = {'insets': [[476.0], [476.0]],
 'levels': [965, 4978],
 'outlines': [[[(0, 0), (18542, 0), (18542, 12484), (0, 12484)]],
              [[(0, 0), (18542, 0), (18542, 12484), (0, 12484)]]],
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
