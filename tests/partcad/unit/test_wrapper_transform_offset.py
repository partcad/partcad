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

# Imported rather than run: everything it does as a wrapper is under its
# '__main__' guard, which is what lets the wrappers that build a part move it
# with these very functions (see 'wrapper_common.finished').
import wrapper_transform  # noqa: E402


def _relocate(shape, offset):
    """The wrapper's own function."""
    return wrapper_transform.relocate(shape, offset)


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


#
# The same transformation build123d makes, without importing build123d
#


def _old_relocate(shape, offset):
    """What 'relocate()' was: build123d's own Location."""
    import build123d as b3d
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    return BRepBuilderAPI_Transform(shape, b3d.Location(*offset).wrapped.Transformation(), True).Shape()


def _old_scale(shape, factor):
    """What 'scale()' was: build123d's own Shape.scale()."""
    import build123d as b3d

    solid = b3d.Solid.make_box(1, 1, 1)
    solid.wrapped = shape
    return solid.scale(factor).wrapped


def _brep(shape):
    import io

    from OCP.BRepTools import BRepTools

    stream = io.BytesIO()
    BRepTools.Write_s(shape, stream)
    return stream.getvalue()


def _located_box():
    """A box that carries a location of its own, which is what 'scale()' scales about."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 1, 0)), 0.3)
    trsf.SetTranslationPart(gp_Vec(1.5, -2.25, 1 / 3))
    return BRepPrimAPI_MakeBox(1, 2, 3).Shape().Moved(TopLoc_Location(trsf))


OFFSETS = [
    [[10, 0, 0], [0, 0, 1], 0],
    [[0, 0, 0], [1, 0, 0], 90],
    [[1 / 3, -2.5, 1e-9], [1, 1, 0], -17.25],
    [[10, 20, 30], [0.2, -0.7, 3], 721],
    ((1, 2, 3), (0, 1, 0), 45.0),
]


@pytest.mark.parametrize("offset", OFFSETS)
@pytest.mark.parametrize("shape", [BRepPrimAPI_MakeBox(1, 2, 3).Shape, _located_box])
def test_the_packed_offset_moves_a_part_exactly_as_build123d_did(offset, shape):
    """Byte for byte: a cached part moved before this is the part moved now."""
    pytest.importorskip("build123d")
    assert _brep(wrapper_transform.relocate(shape(), offset)) == _brep(_old_relocate(shape(), offset))


@pytest.mark.parametrize("factor", [2, 0.5, 1 / 3, -1.5, 25.4])
@pytest.mark.parametrize("shape", [BRepPrimAPI_MakeBox(1, 2, 3).Shape, _located_box])
def test_a_number_scales_a_part_exactly_as_build123d_did(factor, shape):
    pytest.importorskip("build123d")
    new = wrapper_transform.scale(shape(), factor)
    old = _old_scale(shape(), factor)
    assert _brep(new) == _brep(old)
    assert type(new) is type(old)


def test_another_form_is_left_to_build123d():
    """What PartCAD does not document is whatever build123d makes of it, as it always was."""
    pytest.importorskip("build123d")
    # A position and Euler angles: no angle of its own to rotate by.
    offset = [[1, 2, 3], [10, 20, 30]]
    assert wrapper_transform._packed_transformation(offset) is None
    assert _brep(wrapper_transform.relocate(BRepPrimAPI_MakeBox(1, 1, 1).Shape(), offset)) == _brep(
        _old_relocate(BRepPrimAPI_MakeBox(1, 1, 1).Shape(), offset)
    )
    assert wrapper_transform._packed_transformation([[1, 2, 3], [0, 0, 1], True]) is None
