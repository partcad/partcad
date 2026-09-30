#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An 'offset:' moves the part, and leaves nothing behind that says so.

The transform is applied to the geometry, so what comes back sits at the new
place with an identity location. That second half is not tidiness: it is what
keeps every consumer agreeing about where the part is.

It did not, and the two errors cancelled in a picture. 'relocate()' gives a
shape a new local frame and bakes the inverse into the geometry, so the shape
does not move; the offset then existed only as a location, and exporting
dropped it - seeing the compensating inverse, a part rotated by the opposite of
what was asked - while 'partcad.test.interference' honoured it and saw a part
that had not moved at all. 'feature_enrich:desk-enrich' rendered as a desk
while the check was shown four legs lying across one another, and reported
4.8 million mm^3 of overlap that is not there.
"""

import os
import sys

import pytest

OCP = pytest.importorskip("OCP")

from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "partcad", "wrappers"))


def _relocate(shape, offset):
    """The wrapper's own function, taken without running its __main__."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "src", "partcad", "wrappers", "wrapper_transform.py"
    )
    source = open(path).read()
    start = source.index("def _relocate(")
    end = source.index("\ndef _scale(")
    namespace = {}
    exec(compile(source[start:end], path, "exec"), namespace)
    return namespace["_relocate"](shape, offset)


def _box(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    return box.Get()


def test_a_translation_moves_the_part():
    moved = _relocate(BRepPrimAPI_MakeBox(1, 1, 1).Shape(), [[10, 0, 0], [0, 0, 1], 0])
    x0, _, _, x1, _, _ = _box(moved)
    assert (round(x0, 6), round(x1, 6)) == (10.0, 11.0)


def test_a_rotation_turns_the_part():
    """90 degrees about X takes +Y to +Z."""
    turned = _relocate(BRepPrimAPI_MakeBox(1, 2, 3).Shape(), [[0, 0, 0], [1, 0, 0], 90])
    x0, y0, z0, x1, y1, z1 = _box(turned)
    assert (round(y0, 6), round(y1, 6)) == (-3.0, 0.0)
    assert (round(z0, 6), round(z1, 6)) == (0.0, 2.0)


def test_nothing_is_left_behind_in_a_location():
    """The whole of the offset is in the geometry.

    A consumer that reads the location and one that ignores it have to agree,
    and the only way that is guaranteed is for there to be nothing to read.
    """
    moved = _relocate(BRepPrimAPI_MakeBox(1, 1, 1).Shape(), [[10, 20, 30], [1, 0, 0], 45])
    assert moved.Location().IsIdentity()
