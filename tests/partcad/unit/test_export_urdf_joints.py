#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How the URDF exporter writes bodies and joints: 'Planner' in builtin/export/export_urdf.py.

The plan is plain data - links, joints, their frames, limits and dynamics, in
URDF's units - built from what 'kinematics.bodies()' finds, so it is checked
here without writing a file: one test per row of the classification table
(docs/design/simulation.md, section 8.8), each moving the URDF it plans through
a few configurations and comparing where the child body lands with where the
joint itself puts it. That is what makes the URDF the same mechanism, and not
only the same picture at zero.

What goes through a sandbox - writing the file and reading it back - is in
test_urdf_round_trip.py.
"""

import math
import os
import random
import sys

import pytest

import partcad as pc

from .test_kinematics import TABLE, X, Y, Z, _close_pose, fixed, free

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "export"))
import export_urdf  # noqa: E402
import kinematics  # noqa: E402
import urdf_common  # noqa: E402


def two_bodies(steps, physics=None, record=None, root_location=None):
    """A base and an arm on one joint of the given steps, as the core's tree states them."""
    joint = dict({"name": "j", "parent": "base", "child": "arm", "steps": steps}, **(record or {}))
    if physics:
        joint["physics"] = physics
    location = urdf_common.to_packed(kinematics.Joint(joint).location())
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "kind": "assembly",
        "assembly": [
            {"name": "pkg:base", "label": "base", "kind": "part", "brep": b"b"},
            {"name": "pkg:arm", "label": "arm", "kind": "part", "brep": b"a", "location": location, "joint": joint},
        ],
    }
    if root_location is not None:
        tree["location"] = root_location
    return tree


def plan(tree, **options):
    return export_urdf.Planner(kinematics.bodies(tree), options).plan()


def link_poses(planned, values):
    """Every link's frame in the tree's, the URDF moved to 'values' (joint name -> URDF units)."""
    poses = {}
    for link in planned.links:
        if link.body is not None and link.body.is_root:
            poses[link.name] = kinematics.compose(link.body.world, link.frame)
    if "world" in (link.name for link in planned.links):
        poses["world"] = kinematics.IDENTITY
    joints = {joint.name: joint for joint in planned.joints}
    for joint in planned.joints:
        value = values.get(joint.name, 0.0)
        if joint.mimic is not None:
            leader, multiplier, offset = joint.mimic
            value = multiplier * values.get(leader, 0.0) + offset
            assert leader in joints
        moved = kinematics.compose(kinematics.compose(poses[joint.parent], joint.origin), joint.motion(value))
        poses[joint.child] = moved
    return poses


def body_pose(planned, poses, body):
    link = next(link for link in planned.links if link.body is body)
    return kinematics.compose(poses[link.name], kinematics.inverse(link.frame))


def configurations(joint, count=5, seed=11):
    """The starting values, zero, and random ones within the bounds - a follower following its leader."""
    generator = random.Random(seed)
    sets = [[0.0] * len(joint.freedoms)]
    for _ in range(count):
        values = []
        for freedom in joint.freedoms:
            low = freedom.lower if freedom.lower is not None else (-170.0 if freedom.kind == kinematics.TURN else -50.0)
            high = freedom.upper if freedom.upper is not None else (170.0 if freedom.kind == kinematics.TURN else 50.0)
            values.append(generator.uniform(low, high))
        for freedom in joint.freedoms:
            if freedom.follows is not None:
                values[freedom.index] = freedom.ratio * values[freedom.follows] + (freedom.offset or 0.0)
        sets.append(values)
    return sets


# What each kind is written as: URDF's own type, or a chain of single-axis joints.
NATIVE = {
    kinematics.REVOLUTE: "revolute",
    kinematics.CONTINUOUS: "continuous",
    kinematics.PRISMATIC: "prismatic",
    kinematics.PLANAR: "planar",
    kinematics.FLOATING: "floating",
}

ROWS = [row for row in TABLE if row[2] != kinematics.FIXED]


@pytest.mark.parametrize("steps, kind", [(steps, kind) for _, steps, kind in ROWS], ids=[row[0] for row in ROWS])
def test_every_row_of_the_table_is_written_as_the_same_mechanism(steps, kind):
    planned = plan(two_bodies(steps))
    found = planned.found
    base, arm = found
    joint = arm.joint
    assert joint.kind == kind
    # The root is named after the one part it is made of; the URDF has no
    # 'world', since nothing is welded to it.
    assert [link.name for link in planned.links if not link.dummy] == ["base", "arm"]

    if kind in NATIVE:
        (written,) = planned.joints
        assert (written.name, written.type, written.parent, written.child) == ("j", NATIVE[kind], "base", "arm")
        assert not any(link.dummy for link in planned.links)
    else:
        # One joint per freedom, a dummy link between each two, named after
        # the joint and weighing what an engine accepts.
        assert len(planned.joints) == len(joint.freedoms)
        assert planned.joints[0].name == "j"
        dummies = [link for link in planned.links if link.dummy]
        assert [link.name for link in dummies] == ["j_link%d" % (i + 1) for i in range(len(joint.freedoms) - 1)]
        for dummy in dummies:
            assert dummy.inertial(planned.options)["mass"] == export_urdf.DUMMY_MASS
        expected = [
            ("prismatic" if f.kind == kinematics.MOVE else ("revolute" if f.limited else "continuous"))
            for f in joint.freedoms
        ]
        assert [written.type for written in planned.joints] == expected
        assert any("has no URDF type" in warning for warning in planned.warnings)

    if kind in (kinematics.PLANAR, kinematics.FLOATING):
        # URDF's own: the joint at the native frame, the child at its tail,
        # and a planar joint's axis the normal of its plane.
        (written,) = planned.joints
        assert _close_pose(written.origin, joint.classification.origin)
        if kind == kinematics.PLANAR:
            assert written.axis == joint.classification.axes[2]
        poses = link_poses(planned, {})
        assert _close_pose(
            body_pose(planned, poses, arm),
            kinematics.compose(base.world, joint.location([0.0] * 3 if kind == kinematics.PLANAR else [0.0] * 6)),
        )
        return

    # Every single-axis joint moved to each configuration puts the arm exactly
    # where the joint puts it.
    names = [written.name for written in planned.joints]
    for values in configurations(joint):
        urdf_values = {
            name: export_urdf.to_si(freedom.kind, value) for name, freedom, value in zip(names, joint.freedoms, values)
        }
        poses = link_poses(planned, urdf_values)
        expected = kinematics.compose(base.world, joint.location(values))
        assert _close_pose(body_pose(planned, poses, arm), expected), values


def test_the_child_link_frame_is_the_moving_frame_and_the_axis_is_verbatim():
    """'<axis>' is the freedom's own axis, and the part sits in its link at the joint's tail."""
    steps = [fixed((10, 0, 5), (0, 0, 1), 90), free("turn", (0, 1, 0), -45, 45), fixed((0, 0, 7))]
    planned = plan(two_bodies(steps))
    (written,) = planned.joints
    assert written.axis == (0.0, 1.0, 0.0)
    assert _close_pose(written.origin, ((math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)), (10.0, 0, 5)))
    arm = next(link for link in planned.links if link.name == "arm")
    ((_, where),) = arm.shapes()
    assert _close_pose(where, ((1.0, 0, 0, 0), (0, 0, 7.0)))
    # Radians at the boundary, and nowhere else.
    assert (written.lower, written.upper) == pytest.approx((-math.pi / 4, math.pi / 4))


def test_limits_and_dynamics_are_written_in_urdf_units():
    physics = {"maxEffort": 12.0, "maxVelocity": 180.0, "damping": 0.1, "friction": 0.05, "springStiffness": 3.0}
    (written,) = plan(two_bodies([free("turn", Z, -90, 90)], physics)).joints
    assert (written.effort, written.velocity) == pytest.approx((12.0, math.pi))
    assert (written.damping, written.friction) == (0.1, 0.05)
    assert written.gazebo["springStiffness"] == 3.0
    (slide,) = plan(two_bodies([free("move", X, 0, 50)], {"maxVelocity": 250.0})).joints
    assert (slide.lower, slide.upper, slide.velocity) == pytest.approx((0.0, 0.05, 0.25))


def test_what_urdf_requires_and_the_joint_does_not_state_is_a_reported_default():
    planned = plan(two_bodies([free("turn", Z, None, 90)]), effort=7.0)
    (written,) = planned.joints
    assert (written.effort, written.velocity) == (7.0, export_urdf.DEFAULT_VELOCITY)
    # A bound open on one side is written far away on it, since URDF has two.
    assert written.lower == pytest.approx(-math.radians(export_urdf.OPEN_BOUND))
    assert any("state no 'maxEffort'" in warning for warning in planned.warnings)
    assert any("open on one" in warning for warning in planned.warnings)
    # A continuous joint needs no '<limit>' at all.
    (spin,) = plan(two_bodies([free("turn", Z)])).joints
    assert (spin.type, spin.effort, spin.lower) == ("continuous", None, None)


def test_the_starting_value_is_lost_and_said_to_be():
    planned = plan(two_bodies([free("turn", Z, -90, 90, value=30.0)]))
    base, arm = planned.found
    # Written at zero: the arm is where the joint at zero puts it.
    poses = link_poses(planned, {})
    assert _close_pose(body_pose(planned, poses, arm), kinematics.compose(base.world, arm.joint.location([0.0])))
    assert any("'j' at 30 deg" in warning for warning in planned.warnings)


def test_a_screw_is_a_turn_and_a_move_that_mimics_it_by_the_lead():
    lead = 0.5 / 360.0  # mm a degree
    steps = [free("turn", Z, -720, 720), free("move", Z, coupling={"step": 0, "ratio": lead, "offset": 0.25})]
    planned = plan(two_bodies(steps))
    turn, move = planned.joints
    assert (turn.type, move.type) == ("revolute", "prismatic")
    leader, multiplier, offset = move.mimic
    # Metres a radian: 0.5 mm a turn is 0.5e-3 / (2 pi).
    assert (leader, multiplier, offset) == ("j", pytest.approx(0.5e-3 / (2 * math.pi)), pytest.approx(0.25e-3))
    # The turn pays for moving it; the move follows.
    assert move.damping is None
    assert any("approximate" in warning for warning in planned.warnings)


def test_a_mimic_between_two_joints_is_written_in_urdf_units():
    pan = {"name": "pan", "parent": "base", "child": "arm", "steps": [free("turn", Z, -90, 90)]}
    slide = {
        "name": "slide",
        "parent": "arm",
        "child": "carriage",
        "steps": [fixed((0, 0, 10)), free("move", X, 0, 20)],
        "mimic": {"joint": "pan", "multiplier": 0.1, "offset": 5.0},
    }
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "kind": "assembly",
        "assembly": [
            {"name": "pkg:base", "label": "base", "kind": "part", "brep": b"b"},
            {"name": "pkg:arm", "label": "arm", "kind": "part", "brep": b"a", "joint": pan},
            {"name": "pkg:c", "label": "carriage", "kind": "part", "brep": b"c", "joint": slide},
        ],
    }
    planned = plan(tree)
    written = {joint.name: joint for joint in planned.joints}
    # 0.1 mm a degree is 0.1e-3 m per (pi / 180) rad; 5 mm is 5e-3 m.
    assert written["slide"].mimic == ("pan", pytest.approx(0.1e-3 * 180.0 / math.pi), pytest.approx(5.0e-3))


def test_soft_limits_are_a_safety_controller():
    record = {"softLimits": {"lower": -80.0, "upper": 80.0, "kPosition": 10.0, "kVelocity": 2.0}}
    (written,) = plan(two_bodies([free("turn", Z, -90, 90)], record=record)).joints
    assert written.safety == pytest.approx((2.0, 10.0, -math.radians(80.0), math.radians(80.0)))


def test_a_free_root_is_the_root_link_where_the_tree_put_it():
    """No 'world', and no fixed joint to one: a free body is free, and its shapes are where they were."""
    planned = plan(two_bodies([free("turn", Z, -90, 90)], root_location=[[100, 0, 0], [0, 0, 1], 90]))
    assert [link.name for link in planned.links] == ["base", "arm"]
    base_link = planned.links[0]
    ((part, where),) = base_link.shapes()
    assert _close_pose(where, part.world)
    base, arm = planned.found
    poses = link_poses(planned, {})
    assert _close_pose(body_pose(planned, poses, arm), arm.world)


def test_a_scene_hangs_off_the_world_fixed_where_fixed_and_floating_where_free():
    tree = {
        "name": "pkg:room",
        "label": "room",
        "kind": "scene",
        "assembly": [
            {"name": "pkg:table", "label": "table", "kind": "part", "fixed": True, "brep": b"t"},
            {
                "name": "pkg:block",
                "label": "block",
                "kind": "part",
                "brep": b"b",
                "location": [[0, 0, 50], [0, 0, 1], 0],
            },
        ],
    }
    planned = plan(tree)
    assert [link.name for link in planned.links] == ["world", "table", "block"]
    assert [(joint.type, joint.parent, joint.child) for joint in planned.joints] == [
        ("fixed", "world", "table"),
        ("floating", "world", "block"),
    ]
    assert _close_pose(planned.joints[1].origin, ((1.0, 0, 0, 0), (0, 0, 50.0)))
    assert any("'floating' joint" in warning for warning in planned.warnings)


def test_a_body_fixed_to_the_world_on_its_own_hangs_off_the_world():
    tree = {
        "name": "pkg:room",
        "label": "room",
        "kind": "scene",
        "assembly": [{"name": "pkg:table", "label": "table", "kind": "part", "fixed": True, "brep": b"t"}],
    }
    planned = plan(tree)
    assert [(joint.type, joint.parent, joint.child) for joint in planned.joints] == [("fixed", "world", "table")]
    assert planned.warnings == []


def test_a_chain_read_from_several_urdf_joints_gives_them_their_names_back():
    """A joint the reader composed from two URDF joints through a link of no geometry is two joints again."""
    first = dict(free("turn", Z, -90, 90), source=[{"parameter": "angle", "joint": "roll"}])
    second = dict(free("turn", Y, -45, 45), source=[{"parameter": "angle", "joint": "pitch"}])
    planned = plan(two_bodies([first, fixed((0, 0, 20)), second], record={"name": "roll"}))
    assert [joint.name for joint in planned.joints] == ["roll", "pitch"]
    assert [link.name for link in planned.links] == ["base", "roll_link1", "arm"]


def test_a_link_with_no_geometry_still_states_what_its_body_does(monkeypatch):
    """A body with nothing to draw keeps its stated mass and its Gazebo settings, and is not warned about.

    'build_link' builds 'urdf_parser_py' objects, which are not installed where
    these tests run, so the few it uses are stood in for by records of their
    keyword arguments - which is all that is read back here.
    """
    import types

    urdf = types.ModuleType("urdf_parser_py.urdf")

    class _Record:
        KEYS = ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")

        def __init__(self, *args, **kwargs):
            self.args, self.__dict__["inertial"] = args, None
            self.__dict__.update(kwargs)

        def add_aggregate(self, kind, value):
            raise AssertionError("a link with no geometry was given a %s" % kind)

    for name in ("Link", "Collision", "Mesh", "Visual", "Inertial", "Inertia", "Pose", "Color", "LinkMaterial"):
        setattr(urdf, name, type(name, (_Record,), {}))
    package = types.ModuleType("urdf_parser_py")
    package.urdf = urdf
    monkeypatch.setitem(sys.modules, "urdf_parser_py", package)
    monkeypatch.setitem(sys.modules, "urdf_parser_py.urdf", urdf)

    physics = {"mass": 2.0, "centerOfMass": [0.0, 0.0, 10.0], "inertia": {"ixx": 1e-3, "iyy": 1e-3, "izz": 2e-3}}
    body = types.SimpleNamespace(parts=[], physics=physics, node={"name": "pkg:hub"})
    state = {
        "options": {"inertial": True},
        "planner": types.SimpleNamespace(options={}),
        "gazebo": [],
        "unsupported": set(),
        "properties": {"pkg:hub": {"physics": dict(physics, friction=0.4)}},
        "warnings": [],
    }

    link = export_urdf.build_link(export_urdf.LinkPlan("hub", body=body), state)

    assert link.inertial is not None and link.inertial.mass == 2.0
    assert link.inertial.origin.xyz == [0.0, 0.0, 0.01]
    assert len(state["gazebo"]) == 1 and "mu1" in __import__("xml.etree.ElementTree").etree.ElementTree.tostring(
        state["gazebo"][0], encoding="unicode"
    )
    assert state["warnings"] == []

    # And the 'world', which is no body at all, states nothing.
    world = export_urdf.build_link(export_urdf.LinkPlan("world"), dict(state, gazebo=[]))
    assert world.inertial is None
