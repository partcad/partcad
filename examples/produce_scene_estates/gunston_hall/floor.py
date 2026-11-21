#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's floor: the blocks its rooms are in, inside their walls and a
# millimetre clear of them, 200 mm thick under the storey's level - or one of
# the parts of it a storey too large for one picture is pictured in ('main', the
# main block's, then 'wings', or 'wing' and 'additions'). Written by
# '../make_estate.py' from 'estate.json'; run that again rather than edit it.

from build123d import Kind, Location, Polygon, extrude, offset

DATA = {'insets': [[476.0], [476.0]],
 'levels': [965, 4978],
 'outlines': [[[(0, 0), (18542, 0), (18542, 12484), (0, 12484)]],
              [[(0, 0), (18542, 0), (18542, 12484), (0, 12484)]]],
 'parts': [[], []],
 'slab': 200.0}

storey = 1
part = ""


def floor(index):
    found = None
    level = DATA["levels"][index]
    for outline, inset in zip(DATA["outlines"][index], DATA["insets"][index]):
        face = offset(Polygon(*[tuple(p) for p in outline], align=None), amount=-inset, kind=Kind.INTERSECTION)
        slab = extrude(face.moved(Location((0, 0, level - DATA["slab"]))), amount=DATA["slab"])
        found = slab if found is None else found + slab
    if not part:
        return found
    # Part by part: each the floor within its blocks' outlines, less what the parts before it took, and the last
    # whatever is left - so that the parts are the whole floor, and share nothing.
    parts = DATA["parts"][index]
    taken = None
    for name, outlines in parts:
        region = None
        for outline in outlines:
            face = Polygon(*[tuple(p) for p in outline], align=None).moved(Location((0, 0, level - DATA["slab"] - 1)))
            prism = extrude(face, amount=DATA["slab"] + 2)
            region = prism if region is None else region + prism
        if name == part:
            piece = found if name == parts[-1][0] else found & region
            return piece if taken is None else piece - taken
        taken = region if taken is None else taken + region
    raise ValueError("storey %s is not pictured in parts, and has no part '%s'" % (storey, part))


result = floor(int(storey) - 1)

if "show_object" in locals():
    show_object(result, name="floor-%s" % storey)  # noqa: F821
