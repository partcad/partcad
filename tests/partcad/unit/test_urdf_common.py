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


@pytest.mark.parametrize(
    "rpy",
    [
        (0.5, math.pi / 2, 0.5),
        # 'rpy="0 1.5708 0.5"' is common in real URDF, and it is the case that
        # tells a gimbal-lock branch reading the wrong matrix entries apart from
        # one reading the right ones: the rotation has to survive, not just the
        # pitch.
        (0.0, math.pi / 2, math.radians(30.0)),
        (0.0, -math.pi / 2, math.radians(30.0)),
        (0.0, -math.pi / 2, math.radians(-120.0)),
    ],
)
def test_rpy_gimbal_lock(rpy):
    """At pitch = +-90 degrees only (yaw -+ roll) is determined; roll is pinned to 0."""
    q = urdf_common.rpy_to_quat(rpy)
    roll, pitch, _ = urdf_common.quat_to_rpy(q)
    assert roll == 0.0
    assert pitch == pytest.approx(rpy[1])
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


#
# Turning a volume and a material into a mass and an inertia
#


def test_a_material_density_becomes_kg_per_cubic_metre():
    """PartCAD states g/mm^3; URDF and SDFormat state kg/m^3."""
    # PLA at 1.32 g/cm^3, which is 0.00132 g/mm^3, is 1320 kg/m^3.
    assert urdf_common.density_from_material({"density": 0.00132}) == pytest.approx(1320.0)
    assert urdf_common.density_from_material({"density": 0.00785}) == pytest.approx(7850.0)


def test_a_material_with_nothing_usable_has_no_density():
    # Each of these means "weigh it some other way", never "weigh it as zero".
    assert urdf_common.density_from_material(None) is None
    assert urdf_common.density_from_material({}) is None
    assert urdf_common.density_from_material({"name": "PLA"}) is None
    assert urdf_common.density_from_material({"density": None}) is None
    assert urdf_common.density_from_material({"density": 0.0}) is None
    assert urdf_common.density_from_material({"density": "heavy"}) is None


def _box(a, b, c, centre, density):
    """A box as 'combine_inertials' takes it: unit-density moments about its own centre."""
    volume = a * b * c
    inertia = [
        [volume * (b * b + c * c) / 12.0, 0.0, 0.0],
        [0.0, volume * (a * a + c * c) / 12.0, 0.0],
        [0.0, 0.0, volume * (a * a + b * b) / 12.0],
    ]
    return (volume, centre, inertia, density)


def test_one_solid_is_its_own_volume_times_its_density():
    mass, centre, inertia = urdf_common.combine_inertials([_box(10.0, 20.0, 30.0, (5.0, 10.0, 15.0), 2700.0)])
    # 6000 mm^3 of aluminium.
    assert mass == pytest.approx(6000.0 * 1e-9 * 2700.0)
    # The centre of mass comes back in metres.
    assert centre == pytest.approx((0.005, 0.010, 0.015))
    # ixx = V(b^2+c^2)/12 * density * mm^5->m^5.
    assert inertia["ixx"] == pytest.approx(650000.0 * 2700.0 * 1e-15)
    assert inertia["ixy"] == pytest.approx(0.0)


def test_a_link_of_two_materials_weighs_what_both_say():
    """The case one density for the whole link cannot express.

    A steel insert in a plastic housing weighs what neither material alone
    would say, and the centre of mass is pulled towards the steel.
    """
    plastic = _box(20.0, 20.0, 5.0, (0.0, 0.0, 0.0), 1320.0)
    steel = _box(20.0, 20.0, 5.0, (40.0, 0.0, 0.0), 7850.0)
    mass, centre, _ = urdf_common.combine_inertials([plastic, steel])

    plastic_mass = 2000.0 * 1e-9 * 1320.0
    steel_mass = 2000.0 * 1e-9 * 7850.0
    assert mass == pytest.approx(plastic_mass + steel_mass)
    # Weighted towards the steel, not the midpoint at 0.020 m.
    expected_x = (plastic_mass * 0.0 + steel_mass * 0.040) / (plastic_mass + steel_mass)
    assert centre[0] == pytest.approx(expected_x)
    assert centre[0] > 0.030


def test_combining_carries_each_tensor_to_the_shared_centre():
    """Two identical solids apart on one axis, against the closed form.

    Each contributes its own tensor plus m*d^2 about the combined centre, which
    for this arrangement is the midpoint.
    """
    a = b = c = 10.0
    half = 25.0
    left = _box(a, b, c, (-half, 0.0, 0.0), 1000.0)
    right = _box(a, b, c, (half, 0.0, 0.0), 1000.0)
    mass, centre, inertia = urdf_common.combine_inertials([left, right])

    each = 1000.0 * 1e-9 * 1000.0  # 1000 mm^3 at 1000 kg/m^3
    assert mass == pytest.approx(2.0 * each)
    assert centre == pytest.approx((0.0, 0.0, 0.0))
    # About x the offset is along the axis, so nothing is added.
    own_ixx = 1000.0 * (b * b + c * c) / 12.0 * 1000.0 * 1e-15
    assert inertia["ixx"] == pytest.approx(2.0 * own_ixx)
    # About y and z each solid is carried 0.025 m off the centre.
    own_izz = 1000.0 * (a * a + b * b) / 12.0 * 1000.0 * 1e-15
    assert inertia["izz"] == pytest.approx(2.0 * (own_izz + each * 0.025**2))


def test_solids_with_no_volume_are_left_out():
    real = _box(10.0, 10.0, 10.0, (0.0, 0.0, 0.0), 1000.0)
    empty = (0.0, (0.0, 0.0, 0.0), [[0.0] * 3] * 3, 1000.0)
    assert urdf_common.combine_inertials([real, empty]) == urdf_common.combine_inertials([real])


def test_nothing_to_weigh_is_none_not_zero():
    # A mesh or an open shell has no volume. None is what makes the caller
    # write no <inertial> at all rather than one full of zeroes.
    assert urdf_common.combine_inertials([]) is None
    assert urdf_common.combine_inertials([(0.0, (0.0, 0.0, 0.0), [[0.0] * 3] * 3, 2700.0)]) is None
