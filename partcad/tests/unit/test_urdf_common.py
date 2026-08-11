#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the URDF/PartCAD pose conversions.

These are the arithmetic the two URDF wrappers rest on, and they are pure
Python, so they are tested here directly rather than through a sandbox.
"""

import math
import os
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import urdf_common  # noqa: E402


class _Origin:
    """The duck type urdf_parser_py hands back for an ``<origin>``."""

    def __init__(self, xyz=None, rpy=None):
        self.xyz = xyz
        self.rpy = rpy


def _rotation_matrix(q):
    """The 3x3 rotation matrix of a quaternion, for comparing rotations."""
    return [urdf_common.rotate_vec(q, axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]


def _assert_same_rotation(a, b, tolerance=1e-9):
    for row_a, row_b in zip(_rotation_matrix(a), _rotation_matrix(b)):
        for value_a, value_b in zip(row_a, row_b):
            assert value_a == pytest.approx(value_b, abs=tolerance)


@pytest.mark.parametrize(
    "rpy",
    [
        (0.0, 0.0, 0.0),
        (0.3, 0.0, 0.0),
        (0.0, -0.7, 0.0),
        (0.0, 0.0, math.pi / 2),
        (0.4, -0.2, 1.9),
        (-2.9, 1.1, 0.6),
    ],
)
def test_rpy_round_trip(rpy):
    """rpy -> quaternion -> rpy reproduces the same rotation."""
    q = urdf_common.rpy_to_quat(rpy)
    _assert_same_rotation(q, urdf_common.rpy_to_quat(urdf_common.quat_to_rpy(q)))


def test_rpy_is_fixed_axis_zyx():
    """URDF's rpy applies about the fixed X, Y then Z axes.

    A quarter turn about Z takes the X axis onto the Y axis; a quarter turn
    about Y takes it onto -Z. Getting the order wrong swaps the two.
    """
    yaw = urdf_common.rpy_to_quat((0.0, 0.0, math.pi / 2))
    assert urdf_common.rotate_vec(yaw, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)

    both = urdf_common.rpy_to_quat((0.0, math.pi / 2, math.pi / 2))
    # Rz(90) . Ry(90) applied to X: Ry sends X to -Z, which Rz leaves alone.
    assert urdf_common.rotate_vec(both, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)


def test_rpy_gimbal_lock():
    """At pitch = 90 degrees only (roll -+ yaw) is determined; roll is pinned to 0."""
    q = urdf_common.rpy_to_quat((0.5, math.pi / 2, 0.5))
    roll, pitch, _ = urdf_common.quat_to_rpy(q)
    assert roll == 0.0
    assert pitch == pytest.approx(math.pi / 2)
    _assert_same_rotation(q, urdf_common.rpy_to_quat(urdf_common.quat_to_rpy(q)), tolerance=1e-7)


def test_urdf_origin_is_metres_partcad_is_millimetres():
    pose = urdf_common.from_urdf_origin(_Origin(xyz=[0.1, -0.02, 3.0], rpy=[0.0, 0.0, 0.0]))
    assert pose[1] == pytest.approx((100.0, -20.0, 3000.0))

    xyz, rpy = urdf_common.to_urdf_origin(pose)
    assert xyz == pytest.approx([0.1, -0.02, 3.0])
    assert rpy == pytest.approx([0.0, 0.0, 0.0])


def test_missing_urdf_origin_is_the_identity():
    assert urdf_common.is_identity(urdf_common.from_urdf_origin(None))
    assert urdf_common.is_identity(urdf_common.from_urdf_origin(_Origin()))


def test_packed_round_trip_matches_partcad_location():
    """The packed form this module reads and writes is partcad.geom.Location's."""
    packed = [[1.0, -2.0, 3.5], [0.0, 1.0, 0.0], 30.0]
    pose = urdf_common.from_packed(packed)
    assert pose[1] == pytest.approx((1.0, -2.0, 3.5))

    round_tripped = urdf_common.to_packed(pose)
    reference = pc.Location(packed)
    assert round_tripped[0] == pytest.approx(reference.as_packed()[0])
    _assert_same_rotation(pose[0], urdf_common.from_packed(reference.as_packed())[0])


def test_compose_matches_location_multiplication():
    """Composition is 'parent then child', the same as Location.__mul__."""
    parent = [[10.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0]
    child = [[0.0, 5.0, 0.0], [1.0, 0.0, 0.0], 45.0]

    composed = urdf_common.to_packed(
        urdf_common.compose(urdf_common.from_packed(parent), urdf_common.from_packed(child))
    )
    expected = (pc.Location(parent) * pc.Location(child)).as_packed()

    assert composed[0] == pytest.approx(expected[0], abs=1e-9)
    _assert_same_rotation(urdf_common.from_packed(composed)[0], urdf_common.from_packed(expected)[0])


def test_urdf_to_partcad_to_urdf_preserves_a_pose():
    """A URDF origin survives the trip through PartCAD's representation."""
    origin = _Origin(xyz=[0.12, -0.34, 0.56], rpy=[0.3, -1.1, 2.0])
    xyz, rpy = urdf_common.to_urdf_origin(urdf_common.from_urdf_origin(origin))
    assert xyz == pytest.approx(origin.xyz)
    _assert_same_rotation(urdf_common.rpy_to_quat(rpy), urdf_common.rpy_to_quat(origin.rpy))


def test_is_identity():
    assert urdf_common.is_identity((urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T))
    assert not urdf_common.is_identity((urdf_common.IDENTITY_Q, (0.0, 0.0, 1.0)))
    assert not urdf_common.is_identity((urdf_common.axis_angle_to_quat((0, 0, 1), 5.0), urdf_common.IDENTITY_T))
