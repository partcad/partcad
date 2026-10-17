#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the URDF reader states about joints: 'builtin/import/import_urdf.py', in process.

The reader runs in a sandbox, where nothing measures it, so the parts of it
that are plain arithmetic over what 'urdf_parser_py' parsed are checked here
on stand-ins for its objects: the freedoms each joint type keeps, the axis a
joint with none turns about, a mimic in PartCAD's units, and the joint each
link node carries - checked against 'kinematics', which is what reads it.
test_urdf_round_trip.py runs the reader itself, end to end.
"""

import math
import os
import sys
from types import SimpleNamespace

import pytest

import partcad as pc

from .test_kinematics import _close_pose

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "import"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "export"))
import export_urdf  # noqa: E402
import import_urdf  # noqa: E402
import kinematics  # noqa: E402
import urdf_common  # noqa: E402


def context():
    return {
        "dropped": import_urdf.Dropped(),
        "gazebo": {},
        "strict": False,
        "warnings": [],
        "precision": 9,
        "links": {},
    }


def joint(name, joint_type, axis=None, limit=None, mimic=None, origin=None, **extra):
    fields = dict(
        name=name,
        type=joint_type,
        parent="a",
        child="b",
        axis=axis,
        limit=limit,
        safety_controller=None,
        mimic=mimic,
        dynamics=None,
        calibration=None,
        origin=origin,
    )
    fields.update(extra)
    return SimpleNamespace(**fields)


def limit(lower, upper, effort=1.0, velocity=1.0):
    return SimpleNamespace(lower=lower, upper=upper, effort=effort, velocity=velocity)


def test_a_joint_with_no_axis_turns_about_urdfs_default_x():
    record = import_urdf.joint_record(joint("j", "revolute", limit=limit(-1.0, 1.0)), context())
    assert record["motion"]["axis"] == [1.0, 0.0, 0.0]
    (freedom,) = record["freedoms"]
    assert (freedom["name"], freedom["kind"], freedom["axis"]) == ("angle", "turn", (1.0, 0.0, 0.0))
    assert (freedom["lower"], freedom["upper"]) == pytest.approx((-math.degrees(1.0), math.degrees(1.0)))
    # A fixed or floating joint has no axis to default.
    assert "axis" not in import_urdf.joint_record(joint("f", "fixed"), context())["motion"]


@pytest.mark.parametrize(
    "joint_type, axis, expected",
    [
        ("continuous", [0, 0, 1], [("angle", "turn", (0, 0, 1), None, None)]),
        ("prismatic", [0, 2, 0], [("offset", "move", (0, 1, 0), -100.0, 50.0)]),
        (
            "planar",
            [0, 0, 1],
            [("moveX", "move", (1, 0, 0)), ("moveY", "move", (0, 1, 0)), ("turnZ", "turn", (0, 0, 1))],
        ),
        (
            "planar",
            [0, 0, -1],
            [("moveY", "move", (0, 1, 0)), ("moveX", "move", (1, 0, 0)), ("angle", "turn", (0, 0, -1))],
        ),
        ("fixed", None, []),
    ],
)
def test_each_joint_type_keeps_its_freedoms(joint_type, axis, expected):
    record = import_urdf.joint_record(joint("j", joint_type, axis=axis, limit=limit(-0.1, 0.05)), context())
    freedoms = record["freedoms"]
    assert [f["name"] for f in freedoms] == [entry[0] for entry in expected]
    for freedom, entry in zip(freedoms, expected):
        assert freedom["kind"] == entry[1]
        assert freedom["axis"] == pytest.approx(entry[2])
        if len(entry) > 3:
            assert (freedom["lower"], freedom["upper"]) == (
                None if entry[3] is None else pytest.approx(entry[3]),
                None if entry[4] is None else pytest.approx(entry[4]),
            )


def test_a_floating_joint_keeps_all_six_and_a_tilted_plane_its_own_axes():
    floating = import_urdf.joint_record(joint("f", "floating"), context())["freedoms"]
    assert [f["name"] for f in floating] == ["moveX", "moveY", "moveZ", "turnX", "turnY", "turnZ"]
    tilted = (0.0, math.sqrt(0.5), math.sqrt(0.5))
    planar = import_urdf.joint_record(joint("p", "planar", axis=list(tilted)), context())["freedoms"]
    # Across a normal in the YZ plane one direction is X itself, which is named so.
    assert [f["name"] for f in planar] == ["offset", "moveX", "angle"]
    u, v, normal = (f["axis"] for f in planar)
    for a, b in ((u, v), (u, normal), (v, normal)):
        assert sum(x * y for x, y in zip(a, b)) == pytest.approx(0.0, abs=1e-12)
    # Right-handed: u x v is the normal.
    assert import_urdf._cross(u, v) == pytest.approx(normal)


def test_a_mimic_is_stated_in_partcads_units_on_both_sides():
    robot = SimpleNamespace(joint_map={"slide": SimpleNamespace(type="prismatic")})
    mimic = SimpleNamespace(joint="slide", multiplier=2.0, offset=0.5)
    record = import_urdf.joint_record(joint("spin", "continuous", axis=[0, 0, 1], mimic=mimic), context(), robot)
    # Two radians a metre are 2 * (180 / pi) degrees per 1000 millimetres.
    assert record["motion"]["mimic"] == {
        "joint": "slide",
        "multiplier": pytest.approx(2.0 * math.degrees(1.0) / 1000.0),
        "offset": pytest.approx(math.degrees(0.5)),
    }


def origin(xyz=(0, 0, 0), rpy=(0, 0, 0)):
    return SimpleNamespace(xyz=list(xyz), rpy=list(rpy))


def _robot_and_joints(urdf_joints):
    robot = SimpleNamespace(joint_map={j.name: j for j in urdf_joints})
    records = {j.name: import_urdf.joint_record(j, context(), robot) for j in urdf_joints}
    return robot, records


def test_a_link_on_a_movable_joint_carries_the_steps_kinematics_reads():
    pan = joint("pan", "revolute", axis=[0, 0, 1], limit=limit(-1.0, 1.0), origin=origin((0, 0, 0.02), (0, 0, 0.3)))
    robot, records = _robot_and_joints([pan])
    found = context()
    shape = urdf_common.to_packed(urdf_common.from_urdf_origin(origin((0, 0, 0.01))))
    found["links"] = {
        "base": {"parent": None, "joints": [], "shape_origin": shape},
        "arm": {"parent": "base", "joints": ["pan"], "shape_origin": shape},
    }
    attachment = import_urdf.link_attachment("arm", records, robot, found)
    record = attachment["joint"]
    assert (record["name"], record["parent"], record["child"]) == ("pan", "base", "arm")
    assert [step["role"] if step["type"] == "fixed" else "free" for step in record["steps"]] == [
        "parentShape",
        "origin",
        "free",
        "shape",
    ]
    # The parent's shape offset undone, the joint origin, the turn, the child's shape offset.
    moved = kinematics.Joint(record)
    assert moved.kind == kinematics.REVOLUTE
    # Composed onto the parent's node frame (the base link at the root, its
    # shape 10 mm up), the steps give the child's: the joint origin, then its
    # own shape offset.
    shape_pose = urdf_common.from_urdf_origin(origin((0, 0, 0.01)))
    expected = urdf_common.compose(urdf_common.from_urdf_origin(pan.origin), shape_pose)
    child_node = urdf_common.compose(shape_pose, moved.location())
    assert child_node[1] == pytest.approx(expected[1])
    assert child_node[0] == pytest.approx(expected[0])
    # The root link is attached to nothing.
    assert import_urdf.link_attachment("base", records, robot, found) == {}


def test_a_link_on_a_fixed_joint_is_attached_and_a_chain_through_no_geometry_is_one_joint():
    fixed = joint("mount", "fixed", origin=origin((0, 0, 0.05)))
    roll = joint("roll", "revolute", axis=[1, 0, 0], limit=limit(-0.5, 0.5), origin=origin((0, 0.03, 0)))
    pitch = joint(
        "pitch",
        "revolute",
        axis=[0, 1, 0],
        limit=limit(-0.7, 0.7),
        mimic=SimpleNamespace(joint="roll", multiplier=0.5, offset=0.0),
    )
    robot, records = _robot_and_joints([fixed, roll, pitch])
    found = context()
    identity = urdf_common.to_packed(kinematics.IDENTITY)
    found["links"] = {
        "base": {"parent": None, "joints": [], "shape_origin": identity},
        "tool": {"parent": "base", "joints": ["mount"], "shape_origin": identity},
        "camera": {"parent": "base", "joints": ["roll", "pitch"], "shape_origin": identity},
    }
    assert import_urdf.link_attachment("tool", records, robot, found) == {"attached": "base"}
    record = import_urdf.link_attachment("camera", records, robot, found)["joint"]
    assert record["name"] == "roll"
    composed = kinematics.Joint(record)
    # The second follows the first, which a mimic between two joints of one
    # chain is: one freedom, coupled.
    first, second = composed.freedoms
    assert (second.follows, second.ratio) == (0, pytest.approx(0.5))
    assert "mimic" not in record
    assert any("pass through links with no geometry" in warning for warning in found["warnings"])


def test_small_writing_helpers():
    assert export_urdf.sanitize_name("//pub/examples:logo", "x") == "pub_examples_logo"
    names = export_urdf.naming.Transcoder(export_urdf.URDF_NAMES)
    assert [names.claim("a"), names.derive("a"), names.claim("", fallback="link")] == ["a", "a-2", "link"]
    state = {"warnings": []}
    assert export_urdf.color_rgba("#E6801A", state) == pytest.approx([0.901961, 0.501961, 0.101961, 1.0])
    assert export_urdf.color_rgba("#E6801A80", state)[3] == pytest.approx(0.501961)
    assert export_urdf.color_rgba("red", state) is None and export_urdf.color_rgba("#GGGGGG", state) is None
    assert len(state["warnings"]) == 2
    block = export_urdf.gazebo_element(
        "pan", {"springStiffness": 3.0, "provideFeedback": True}, export_urdf.GAZEBO_JOINT_PHYSICS
    )
    assert [child.tag for child in block] == ["springStiffness", "provideFeedback"]
    assert export_urdf.gazebo_element("pan", {}, export_urdf.GAZEBO_JOINT_PHYSICS) is None
    xml = export_urdf.with_gazebo("<robot>\n</robot>", [block])
    assert '<gazebo reference="pan">' in xml and xml.endswith("</robot>")
    assert export_urdf.with_gazebo("<robot/>", []) == "<robot/>"


def test_a_body_says_what_its_parts_agree_on_and_reports_where_they_do_not():
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "kind": "assembly",
        "assembly": [
            {"name": "pkg:a", "label": "a", "kind": "part", "brep": b"a"},
            {"name": "pkg:b", "label": "b", "kind": "part", "brep": b"b"},
        ],
    }
    properties = {"pkg:a": {"physics": {"friction": 0.5, "mass": 1.0}}, "pkg:b": {"physics": {"friction": 0.9}}}
    (body,) = kinematics.bodies(tree, properties)
    state = {"properties": properties, "warnings": []}
    assert export_urdf.link_physics(body, state) == {"friction": 0.5}
    assert any("state different 'friction'" in warning for warning in state["warnings"])
    # A free root placed away from the origin keeps its inertia where its parts are.
    tree["location"] = [[100, 0, 0], [0, 0, 1], 90]
    planned = export_urdf.Planner(kinematics.bodies(tree, properties)).plan()
    (link,) = planned.links
    inertial = link.inertial(planned.options)
    assert inertial["mass"] == pytest.approx(1.0)
    assert inertial["centerOfMass"] == pytest.approx([100.0, 0.0, 0.0])


@pytest.mark.parametrize(
    "lower, upper, start",
    [
        (-90.0, 90.0, 0.0),
        # A knee that cannot straighten, and a gripper that cannot close to nought.
        (-154.7, -4.6, -4.6),
        (10.0, 40.0, 10.0),
        (0.0, 40.0, 0.0),
        (None, -5.0, -5.0),
        (None, None, 0.0),
    ],
)
def test_a_joint_starts_at_zero_or_at_the_bound_nearest_it(lower, upper, start):
    assert import_urdf.start_within(lower, upper) == start


def test_every_freedom_states_where_it_starts():
    knee = import_urdf.joint_record(joint("knee", "revolute", axis=[0, 1, 0], limit=limit(-2.7, -0.08)), context())
    (freedom,) = knee["freedoms"]
    assert freedom["start"] == pytest.approx(math.degrees(-0.08))
    slide = import_urdf.joint_record(joint("s", "prismatic", axis=[1, 0, 0], limit=limit(0.01, 0.04)), context())
    assert slide["freedoms"][0]["start"] == pytest.approx(10.0)
    for joint_type in ("continuous", "planar", "floating"):
        record = import_urdf.joint_record(joint("j", joint_type, axis=[0, 0, 1]), context())
        assert all(freedom["start"] == 0.0 for freedom in record["freedoms"]), joint_type
    # Where the start puts the child: the knee turned about its axis, by its start.
    moved = import_urdf.start_motion(joint("knee", "revolute", axis=[0, 1, 0], limit=limit(-2.7, -0.08)))
    assert _close_pose(moved, (urdf_common.axis_angle_to_quat((0, 1, 0), math.degrees(-0.08)), (0, 0, 0)))
    assert import_urdf.start_motion(joint("a", "revolute", axis=[0, 1, 0], limit=limit(-1, 1))) == import_urdf.IDENTITY
