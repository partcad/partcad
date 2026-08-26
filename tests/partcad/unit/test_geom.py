#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import math

import pytest

from OCP.gp import gp_Pnt

import partcad as pc
from partcad.geom import Location


def _matrix(location):
    """Return the 3x4 transformation matrix of a location as a flat list of floats."""
    trsf = location.wrapped.Transformation()
    return [trsf.Value(row, col) for row in range(1, 4) for col in range(1, 5)]


def _apply(location, point):
    """Apply a location to a point and return the resulting coordinates."""
    pnt = gp_Pnt(*[float(c) for c in point])
    pnt.Transform(location.wrapped.Transformation())
    return (pnt.X(), pnt.Y(), pnt.Z())


def _assert_close(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert math.isclose(a, e, rel_tol=1e-9, abs_tol=1e-9), f"{actual} != {expected}"


def test_geom_location_identity():
    _assert_close(_matrix(Location()), _matrix(Location(None)))
    _assert_close(_apply(Location(), (1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))


def test_geom_location_three_argument_form_matches_packed_forms():
    """The three argument form is the same transform as the packed list/tuple forms."""
    three_args = Location((1, 2, 3), (0, 0, 1), 45)
    packed_list = Location([[1, 2, 3], [0, 0, 1], 45])
    packed_tuple = Location(((1, 2, 3), (0, 0, 1), 45))

    _assert_close(_matrix(three_args), _matrix(packed_list))
    _assert_close(_matrix(three_args), _matrix(packed_tuple))


def test_geom_location_rotates_about_the_origin_before_translating():
    """Rotation is about an axis through the origin, the translation is applied afterwards.

    A 90 degree rotation about Z maps (1, 0, 0) onto (0, 1, 0). Only if the translation is
    applied after that rotation does the point end up at (0, 1, 0) + (1, 2, 3). Had the
    translation been applied first, the point would have landed at (-2, 1, 3) instead.
    """
    location = Location((1, 2, 3), (0, 0, 1), 90)
    _assert_close(_apply(location, (1, 0, 0)), (1.0, 3.0, 3.0))


def test_geom_location_normalizes_the_axis():
    """A non unit axis is normalized, exactly as gp_Dir does."""
    _assert_close(
        _matrix(Location((0, 0, 0), (0, 0, 5), 90)),
        _matrix(Location((0, 0, 0), (0, 0, 1), 90)),
    )


def test_geom_location_from_trsf_and_copies():
    trsf = Location.trsf_from_coords((4, 5, 6), (0, 1, 0), 33)
    from_trsf = Location(trsf)
    _assert_close(_matrix(from_trsf), _matrix(Location((4, 5, 6), (0, 1, 0), 33)))
    _assert_close(_matrix(Location(from_trsf.wrapped)), _matrix(from_trsf))
    _assert_close(_matrix(Location(from_trsf)), _matrix(from_trsf))


def test_geom_location_composition_applies_the_right_hand_side_first():
    rotate = Location((0, 0, 0), (0, 0, 1), 90)
    translate = Location((1, 0, 0), (0, 0, 1), 0)

    # Translate first, then rotate: (0,0,0) -> (1,0,0) -> (0,1,0)
    _assert_close(_apply(rotate * translate, (0, 0, 0)), (0.0, 1.0, 0.0))
    # Rotate first, then translate: (0,0,0) -> (0,0,0) -> (1,0,0)
    _assert_close(_apply(translate * rotate, (0, 0, 0)), (1.0, 0.0, 0.0))


def test_geom_location_inverse():
    location = Location((1, 2, 3), (1, 1, 0), 70)
    _assert_close(_matrix(location * location.inverse()), _matrix(Location()))
    _assert_close(_apply(location.inverse(), _apply(location, (7, -3, 2))), (7.0, -3.0, 2.0))


def test_geom_location_rejects_bad_arguments():
    with pytest.raises(ValueError):
        Location((1, 2, 3), (0, 0, 1), None)
    with pytest.raises(ValueError):
        Location((1, 2, 3), None, 45)
    with pytest.raises(ValueError):
        Location(None, (0, 0, 1), 45)
    with pytest.raises(ValueError):
        Location("not a location")


@pytest.mark.parametrize("packed", [[], (), [1], (1, 2), [1, 2, 3, 4]])
def test_geom_location_rejects_wrong_length_packed_form(packed):
    """A packed sequence of the wrong length is a clean ValueError, not an IndexError."""
    with pytest.raises(ValueError):
        Location(packed)


def test_geom_location_copy_is_independent():
    """Copying must not alias the source's TopLoc_Location, which is mutable."""
    source = Location([1, 2, 3], [0, 0, 1], 90)
    copied = Location(source)

    assert copied.wrapped is not source.wrapped
    _assert_close(_matrix(copied), _matrix(source))

    # Mutating the source's wrapped location must not disturb the copy
    before = _matrix(copied)
    source.wrapped.Clear()
    _assert_close(_matrix(copied), before)


def test_geom_location_copy_from_toploc_is_independent():
    """The same holds when constructing straight from a TopLoc_Location."""
    source = Location([4, 5, 6], [0, 1, 0], 30)
    copied = Location(source.wrapped)

    assert copied.wrapped is not source.wrapped
    _assert_close(_matrix(copied), _matrix(source))


def test_partcad_location_is_the_partcad_one():
    """The public pc.Location name is PartCAD's own Location."""
    assert pc.Location is Location
    _assert_close(_matrix(pc.Location((0, 0, 1), (0, 0, 1), 0)), _matrix(Location([[0, 0, 1], [0, 0, 1], 0])))
