#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A URDF's kinematics survive PartCAD: read, converted, exported and read again.

Three ways round, each compared joint by joint and link by link:

* a URDF read as a ``type: urdf`` assembly, exported, and read again;
* a URDF converted to ASSY with ``pc convert assembly -t assy``, and exported;
* an ASSY assembly whose joints are written by hand in ``motion:``, exported and
  read back as a URDF.

"The same" means: every movable joint has its name, its type, its frame, its
axis (as the URDF states it), its limits, its dynamics, its soft limits and what
it mimics; every link that is a rigid body is there under its name; and every
shape is where it was, to a micrometre. What is not kept is said in the tests:
a link on a fixed joint is one rigid body with its parent, so it is a shape of
the parent's link, and a link with no geometry is no part of PartCAD's, so the
chain it was in comes back - asked for with 'composites: massless', since a
URDF has no type for the joint it composes into - through a link with no
'<inertial>' named after the joint.
"""

import asyncio
import math
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import pytest

import partcad as pc

from .test_kinematics import _close_pose

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import kinematics  # noqa: E402
import urdf_common  # noqa: E402

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")


def _box(size):
    return "<visual><origin xyz='0 0 %g'/><geometry><box size='%s'/></geometry></visual>" % (
        size[2] / 2,
        " ".join("%g" % v for v in size),
    )


LINK = "<link name='%s'>%s<inertial><mass value='%g'/><inertia ixx='1e-4' ixy='0' ixz='0' iyy='1e-4' iyz='0' izz='1e-4'/></inertial></link>"

# Every joint type URDF has, a joint with no '<axis>' (URDF's default is X), a
# mimic, a safety controller, dynamics, a fixed joint under a moving link, and
# - in 'ROBOT_WITH_GIMBAL' - two joints through a link with no geometry.
JOINTS = """
  <joint name="pan" type="revolute">
    <origin xyz="0 0 0.02" rpy="0 0 0.3"/>
    <parent link="base"/><child link="upper"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.5" upper="1.25" effort="5" velocity="2"/>
    <dynamics damping="0.2" friction="0.01"/>
    <safety_controller soft_lower_limit="-1.4" soft_upper_limit="1.2" k_position="10" k_velocity="1"/>
  </joint>
  <joint name="tilt" type="revolute">
    <origin xyz="0 0 0.1" rpy="0.1 0 0"/>
    <parent link="upper"/><child link="lower"/>
    <limit lower="0" upper="2" effort="3" velocity="1"/>
  </joint>
  <joint name="slide" type="prismatic">
    <origin xyz="0 0 0.1"/>
    <parent link="lower"/><child link="carriage"/>
    <axis xyz="0 1 0"/>
    <limit lower="-0.05" upper="0.04" effort="20" velocity="0.5"/>
    <dynamics damping="3"/>
  </joint>
  <joint name="spin" type="continuous">
    <origin xyz="0.02 0 0.01"/>
    <parent link="carriage"/><child link="wheel"/>
    <axis xyz="1 0 0"/>
    <mimic joint="pan" multiplier="2" offset="0.1"/>
  </joint>
  <joint name="tool_mount" type="fixed">
    <origin xyz="0 0 0.05" rpy="0 1.5707963 0"/>
    <parent link="carriage"/><child link="tool"/>
  </joint>
  <joint name="glide" type="planar">
    <origin xyz="0.2 0 0"/>
    <parent link="base"/><child link="puck"/>
    <axis xyz="0 0 1"/>
  </joint>
  <joint name="loose" type="floating">
    <origin xyz="0 0 0.05"/>
    <parent link="puck"/><child link="bead"/>
  </joint>
"""

GIMBAL = """
  <joint name="roll" type="revolute">
    <origin xyz="0 0.03 0.05"/>
    <parent link="upper"/><child link="gimbal"/>
    <axis xyz="1 0 0"/>
    <limit lower="-0.5" upper="0.5" effort="1" velocity="1"/>
  </joint>
  <link name="gimbal"/>
  <joint name="pitch" type="revolute">
    <origin xyz="0 0 0" rpy="0 0 0.2"/>
    <parent link="gimbal"/><child link="camera"/>
    <axis xyz="0 1 0"/>
    <limit lower="-0.7" upper="0.7" effort="1" velocity="1"/>
  </joint>
"""

LINKS = {
    "base": (0.1, 0.1, 0.02),
    "upper": (0.02, 0.02, 0.1),
    "lower": (0.02, 0.03, 0.1),
    "carriage": (0.04, 0.02, 0.02),
    "wheel": (0.01, 0.03, 0.03),
    "tool": (0.01, 0.01, 0.04),
    "puck": (0.05, 0.05, 0.01),
    "bead": (0.01, 0.01, 0.01),
}


def robot_urdf(gimbal=False):
    links = dict(LINKS, **({"camera": (0.02, 0.02, 0.02)} if gimbal else {}))
    body = "".join(LINK % (name, _box(size), 0.1) for name, size in links.items())
    return "<?xml version='1.0'?>\n<robot name='rig'>%s%s%s\n</robot>\n" % (body, JOINTS, GIMBAL if gimbal else "")


def _package(root, urdf):
    root.mkdir(parents=True, exist_ok=True)
    (root / "rig.urdf").write_text(urdf)
    (root / "partcad.yaml").write_text("assemblies:\n  rig:\n    type: urdf\n")
    return pc.Context(str(root))


def _export(ctx, assembly, directory, name="rig", **options):
    path = os.path.join(str(directory), "%s.urdf" % name)
    asyncio.run(assembly.render_async(ctx, "urdf", filepath=path, tolerance=1.0, angularTolerance=0.5, **options))
    return path


#
# Reading a URDF in the test's own process: ElementTree, URDF's units
#


def _vector(text, default=(0.0, 0.0, 0.0)):
    return tuple(float(v) for v in text.split()) if text else default


def _origin(element):
    origin = element.find("origin") if element is not None else None
    if origin is None:
        return kinematics.IDENTITY

    class Origin:
        xyz = _vector(origin.get("xyz"))
        rpy = _vector(origin.get("rpy"))

    return urdf_common.from_urdf_origin(Origin)


def read_urdf(path):
    """A URDF as plain data: its joints, and where every link and visual is with every joint at zero."""
    robot = ET.parse(path).getroot()
    joints = {}
    for element in robot.findall("joint"):
        joint = {
            "type": element.get("type"),
            "parent": element.find("parent").get("link"),
            "child": element.find("child").get("link"),
            "origin": _origin(element),
        }
        if joint["type"] in ("revolute", "continuous", "prismatic", "planar"):
            axis = element.find("axis")
            joint["axis"] = _vector(axis.get("xyz") if axis is not None else None, (1.0, 0.0, 0.0))
        for tag, keys in (
            ("limit", ("lower", "upper", "effort", "velocity")),
            ("dynamics", ("damping", "friction")),
            ("safety_controller", ("soft_lower_limit", "soft_upper_limit", "k_position", "k_velocity")),
            ("mimic", ("multiplier", "offset")),
        ):
            found = element.find(tag)
            if found is not None:
                joint[tag] = {key: float(found.get(key)) for key in keys if found.get(key) is not None}
                if tag == "mimic":
                    joint[tag]["joint"] = found.get("joint")
        joints[element.get("name")] = joint

    links = {element.get("name"): element for element in robot.findall("link")}
    children = {joint["child"] for joint in joints.values()}
    (root,) = set(links) - children
    frames = {root: kinematics.IDENTITY}
    pending = dict(joints)
    while pending:
        for name, joint in list(pending.items()):
            if joint["parent"] in frames:
                frames[joint["child"]] = kinematics.compose(frames[joint["parent"]], joint["origin"])
                del pending[name]
    visuals = []
    for name, element in links.items():
        for visual in element.findall("visual"):
            visuals.append((kinematics.compose(frames[name], _origin(visual)), name, visual))
    return {"joints": joints, "links": links, "frames": frames, "visuals": visuals, "root": root}


def _close(a, b, tolerance=1e-6):
    return a == pytest.approx(b, abs=tolerance)


def assert_same_joint(name, before, after, renamed=None):
    """One movable joint, as it was: type, links, frame, axis, limits, dynamics, safety, mimic."""
    renamed = renamed or {}
    assert after["type"] == before["type"], name
    assert after["parent"] == renamed.get(before["parent"], before["parent"]), name
    assert after["child"] == renamed.get(before["child"], before["child"]), name
    assert _close_pose(after["origin"], before["origin"], 1e-6), name
    if "axis" in before:
        assert _close(after["axis"], before["axis"], 1e-9), name
    for tag in ("limit", "dynamics", "safety_controller"):
        if tag in before:
            assert set(after.get(tag) or {}) >= set(before[tag]), (name, tag)
            for key, value in before[tag].items():
                assert after[tag][key] == pytest.approx(value, abs=1e-6), (name, tag, key)
    if "mimic" in before:
        assert after["mimic"]["joint"] == before["mimic"]["joint"]
        assert after["mimic"]["multiplier"] == pytest.approx(before["mimic"]["multiplier"])
        assert after["mimic"]["offset"] == pytest.approx(before["mimic"]["offset"])


def assert_same_shapes(before, after):
    """Every visual of the one where a visual of the other is, to a micrometre."""
    remaining = list(after["visuals"])
    for pose, link, _ in before["visuals"]:
        match = next((entry for entry in remaining if _close_pose(entry[0], pose, 1e-6)), None)
        assert match is not None, "nothing exported where %s's shape was" % link
        remaining.remove(match)
    assert remaining == []


def body_of(parsed):
    """The link each link is welded into: itself, or up its fixed joints."""
    up = {joint["child"]: (joint["parent"], joint["type"]) for joint in parsed["joints"].values()}
    result = {}
    for link in parsed["links"]:
        current = link
        while current in up and up[current][1] == "fixed":
            current = up[current][0]
        result[link] = current
    return result


def movable(parsed):
    return {name: joint for name, joint in parsed["joints"].items() if joint["type"] != "fixed"}


#
# The three round trips
#


def test_a_urdf_read_exported_and_read_again_keeps_its_kinematics(tmp_path):
    ctx = _package(tmp_path / "source", robot_urdf(gimbal=True))
    rig = ctx._get_assembly(":rig")
    asyncio.run(rig.do_instantiate())
    # A mechanism as it is read: every movable joint is the joint of the link it moves.
    read = {child.name: child for child in rig.children}
    assert {child.joint.name for child in rig.children if child.joint is not None} == {
        "pan",
        "tilt",
        "slide",
        "spin",
        "glide",
        "loose",
        "roll",
    }
    assert read["tool"].attached == "carriage" and read["tool"].joint is None
    # The joint with no '<axis>' turns about URDF's default, X.
    (tilt,) = read["lower"].joint.free_steps()
    assert tilt.axis == [1.0, 0.0, 0.0]
    # Two joints through a link with no geometry are one, of both freedoms.
    assert [step.axis for step in read["camera"].joint.free_steps()] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    source = read_urdf(tmp_path / "source" / "rig.urdf")
    # The two joints through the gimbal are one universal joint, which a URDF
    # has no type for: exported as the chain it was, through a massless link.
    exported_path = _export(ctx, rig, tmp_path / "out", composites="massless")
    exported = read_urdf(exported_path)

    # Every link that is a body of its own, under its own name - the tool, on a
    # fixed joint, is a shape of the carriage's link - and the gimbal, which has
    # no geometry, comes back as the massless link between the two joints.
    welded = body_of(source)
    assert set(exported["links"]) == {link for link in source["links"] if welded[link] == link} - {"gimbal"} | {
        "roll_link1"
    }
    assert exported["root"] == "base"
    for name, joint in movable(source).items():
        assert_same_joint(name, joint, exported["joints"][name], renamed={"gimbal": "roll_link1"})
    assert_same_shapes(source, exported)
    # It weighs nothing: a frame, as the gimbal link in the source was.
    gimbal = ET.parse(exported_path).getroot().find("link[@name='roll_link1']")
    assert gimbal is not None and gimbal.find("inertial") is None

    # And read again, it is the same mechanism.
    again_root = tmp_path / "out"
    (again_root / "partcad.yaml").write_text("assemblies:\n  rig:\n    type: urdf\n")
    again = pc.Context(str(again_root))._get_assembly(":rig")
    asyncio.run(again.do_instantiate())
    first = {joint.name: kinematics.classify(joint.to_envelope()) for _, joint in rig.joints()}
    second = {joint.name: kinematics.classify(joint.to_envelope()) for _, joint in again.joints()}
    assert set(first) == set(second)
    for name, classification in first.items():
        other = second[name]
        assert other.kind == classification.kind, name
        for mine, theirs in zip(classification.freedoms, other.freedoms):
            assert (theirs.kind, theirs.lower, theirs.upper) == (
                mine.kind,
                pytest.approx(mine.lower),
                pytest.approx(mine.upper),
            ), name
    # The two joints through the gimbal are one universal joint, named after the first.
    assert first["roll"].kind == kinematics.UNIVERSAL


def test_a_urdf_converted_to_assy_exports_as_the_urdf_it_was(tmp_path):
    from partcad.actions.assembly import convert_assembly_action

    ctx = _package(tmp_path / "source", robot_urdf())
    convert_assembly_action(ctx.get_project("//"), "rig", "assy")
    converted = pc.Context(str(tmp_path / "source"))._get_assembly(":rig")
    asyncio.run(converted.do_instantiate())
    assert {joint.name for _, joint in converted.joints()} == {"pan", "tilt", "slide", "spin", "glide", "loose"}
    assert asyncio.run(converted.get_connect_problems()) == []

    source = read_urdf(tmp_path / "source" / "rig.urdf")
    exported = read_urdf(_export(ctx, converted, tmp_path / "out"))
    welded = body_of(source)
    assert set(exported["links"]) == {link for link in source["links"] if welded[link] == link}
    for name, joint in movable(source).items():
        assert_same_joint(name, joint, exported["joints"][name])
    # The converter writes each link's mesh in the link's own frame, so every
    # shape of the export sits where a link of the URDF does: a body's at its
    # link's origin, and the tool at its own link's frame within the carriage's.
    linked = {"visuals": [(pose, name, None) for name, pose in source["frames"].items()]}
    assert_same_shapes(linked, exported)
    for link in exported["links"]:
        assert _close_pose(exported["frames"][link], source["frames"][link], 1e-6), link


HAND_WRITTEN = """
parts:
  base:
    type: stl
    path: cube.stl
    implements:
      bore:
        top: [[0, 0, 10], [0, 0, 1], 0]
      cup:
        side: [[10, 0, 5], [0, 1, 0], 90]
      thread:
        front: [[0, -10, 5], [1, 0, 0], 90]
  arm:
    type: stl
    path: cube.stl
    implements:
      pin:
  lid:
    type: stl
    path: cube.stl
    implements:
      knob:
      bolt:
interfaces:
  bore:
    ports:
      hole:
    parameters:
      turnZ: [-90, 90]
    motion:
      dof: [turnZ]
    physics:
      damping: 0.05
      maxEffort: 2.0
      maxVelocity: 180
  pin:
    ports:
      tip: [[0, 0, 0], [0.71, 0.71, 0], 180]
    mates:
      bore: {}
  cup:
    ports:
      hole:
    motion: ball
  knob:
    ports:
      tip: [[0, 0, 0], [0.71, 0.71, 0], 180]
    mates:
      cup: {}
  thread:
    ports:
      hole:
    threadStep: 2.0
    motion: screw
  bolt:
    ports:
      tip: [[0, 0, 0], [0.71, 0.71, 0], 180]
    mates:
      thread: {}
assemblies:
  rig:
    type: assy
    path: rig.assy
"""

HAND_WRITTEN_ASSY = """
links:
  - part: base
  - part: arm
    connect: {name: base, with: pin, to: bore, joint: shoulder, toParams: {turnZ: 30}}
  - part: lid
    name: ball_end
    connect: {name: base, with: knob, to: cup, joint: wrist}
  - part: lid
    name: nut
    connect: {name: base, with: bolt, to: thread, joint: spin}
"""


def test_hand_written_joints_go_out_as_urdf_and_come_back(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    shutil.copy(CUBE, root / "cube.stl")
    (root / "partcad.yaml").write_text(HAND_WRITTEN)
    (root / "rig.assy").write_text(HAND_WRITTEN_ASSY)
    ctx = pc.Context(str(root))
    rig = ctx._get_assembly(":rig")
    asyncio.run(rig.do_instantiate())
    kinds = {joint.name: kinematics.classify(joint.to_envelope()).kind for _, joint in rig.joints()}
    assert kinds == {"shoulder": kinematics.REVOLUTE, "wrist": kinematics.BALL, "spin": kinematics.SCREW}

    # A ball and a screw have no URDF type: the export refuses them, and writes
    # nothing...
    refused = tmp_path / "refused"
    refused.mkdir()
    _export(ctx, rig, refused)
    assert list(refused.iterdir()) == []
    # ...unless asked to write them as chains through massless links.
    out = tmp_path / "out"
    exported = read_urdf(_export(ctx, rig, out, composites="massless"))
    joints = exported["joints"]
    shoulder = joints["shoulder"]
    assert (shoulder["type"], shoulder["parent"], shoulder["child"]) == ("revolute", "base", "arm")
    assert (shoulder["limit"]["lower"], shoulder["limit"]["upper"]) == pytest.approx((-math.pi / 2, math.pi / 2))
    assert (shoulder["limit"]["effort"], shoulder["limit"]["velocity"]) == pytest.approx((2.0, math.pi))
    assert shoulder["dynamics"]["damping"] == pytest.approx(0.05)
    # A ball is three turns through two massless links, named after the joint.
    wrist = [name for name, joint in joints.items() if name.startswith("wrist")]
    assert len(wrist) == 3 and {"wrist_link1", "wrist_link2"} <= set(exported["links"])
    # A screw is a turn and a move that mimics it by the lead: 2 mm a turn.
    spin = [joint for name, joint in joints.items() if name.startswith("spin")]
    turn, move = sorted(spin, key=lambda joint: joint["type"] != "continuous")
    assert move["type"] == "prismatic" and move["mimic"]["joint"] == "spin"
    assert move["mimic"]["multiplier"] == pytest.approx(2.0e-3 / (2 * math.pi))

    (out / "partcad.yaml").write_text("assemblies:\n  rig:\n    type: urdf\n")
    back = pc.Context(str(out))._get_assembly(":rig")
    asyncio.run(back.do_instantiate())
    read = {joint.name: kinematics.classify(joint.to_envelope()) for _, joint in back.joints()}
    assert {name: classification.kind for name, classification in read.items()} == kinds
    (turn,) = read["shoulder"].freedoms
    assert (turn.lower, turn.upper) == pytest.approx((-90.0, 90.0))


# A leg whose knee cannot straighten: its limits, as a legged robot's often are,
# leave URDF's zero out, and its ankle's do not.
KNEE = """
  <joint name="knee" type="revolute">
    <origin xyz="0 0 -0.1"/>
    <parent link="thigh"/><child link="shin"/>
    <axis xyz="0 1 0"/>
    <limit lower="-2.7" upper="-0.08" effort="10" velocity="5"/>
  </joint>
  <joint name="ankle" type="revolute">
    <origin xyz="0 0 -0.1"/>
    <parent link="shin"/><child link="foot"/>
    <axis xyz="0 1 0"/>
    <limit lower="-0.5" upper="0.5" effort="5" velocity="5"/>
  </joint>
"""


def leg_urdf():
    links = {"thigh": (0.02, 0.02, 0.1), "shin": (0.02, 0.02, 0.1), "foot": (0.05, 0.02, 0.01)}
    body = "".join(LINK % (name, _box(size), 0.1) for name, size in links.items())
    return "<?xml version='1.0'?>\n<robot name='rig'>%s%s\n</robot>\n" % (body, KNEE)


def _start_of(assembly, link):
    child = next(child for child in assembly.children if child.name == link)
    (free,) = child.joint.free_steps()
    return free


def test_a_joint_whose_limits_leave_zero_out_starts_at_the_nearest_bound(tmp_path):
    """A knee bounded to -2.7 .. -0.08 rad starts bent at -0.08, read as a URDF and converted alike.

    Started at URDF's zero it would start against its own stop: an engine
    throws it back in with its first step, and the 'connect' check fails it. So
    the reader places the shin, and everything below it, with the knee at the
    bound nearest zero, the converter writes that bound as the parameter's
    default and the connection's 'toParams', and the assembly is drawn there.
    The URDF exported again is the URDF it was, at its own zero.
    """
    from partcad.actions.assembly import convert_assembly_action

    ctx = _package(tmp_path / "source", leg_urdf())
    read = ctx._get_assembly(":rig")
    asyncio.run(read.do_instantiate())
    knee = _start_of(read, "shin")
    start = math.degrees(-0.08)
    assert (knee.value, knee.lower, knee.upper) == pytest.approx((start, math.degrees(-2.7), start))
    # The ankle's range has zero in it: it starts there, as the URDF places it.
    assert _start_of(read, "foot").value == 0.0
    # Placed where the steps at those values put it - the shin bent, and the foot with it.
    placed = {child.name: child for child in read.children}
    for name in ("shin", "foot"):
        child = placed[name]
        parent = placed[child.joint.parent]
        product = parent.location * child.joint.composition.location()
        # To the reader's rounding of a placement, a micrometre's thousandth.
        assert product.translation == pytest.approx(child.location.translation, abs=1e-5), name
        assert kinematics.outside_bounds(kinematics.Joint(child.joint.to_envelope())) == [], name
    # The foot's box is 100 mm below the knee, less its own 5 mm offset up its link, turned with the shin.
    assert placed["foot"].location.translation[0] == pytest.approx(95.0 * math.sin(0.08), abs=1e-5)

    convert_assembly_action(ctx.get_project("//"), "rig", "assy")
    converted = pc.Context(str(tmp_path / "source"))._get_assembly(":rig")
    asyncio.run(converted.do_instantiate())
    assert asyncio.run(converted.get_connect_problems()) == []
    assert _start_of(converted, "shin").value == pytest.approx(start)
    assy = (tmp_path / "source" / "rig.assy").read_text()
    assert "toParams: {angle: %s}" % round(start, 9) in assy
    assert assy.count("toParams") == 1
    config = (tmp_path / "source" / "partcad.yaml").read_text()
    assert "default: %s" % round(start, 9) in config
    # The converted assembly stands as the read one does. Its parts are each in
    # its link's frame, so it is the link frames that are compared: the shin's
    # at the knee, turned to the start about Y, and the foot's 100 mm down it.
    links = {child.name: child.location for child in converted.children}
    turned = links["thigh"].inverse() * links["shin"]
    axis, angle = turned.as_packed()[1:]
    about_y = angle * (1 if axis[1] > 0 else -1)
    assert (about_y - start + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-6)
    assert turned.translation == pytest.approx((0.0, 0.0, -100.0), abs=1e-5)
    foot = (100.0 * math.sin(0.08), 0.0, -100.0 - 100.0 * math.cos(0.08))
    assert links["foot"].translation == pytest.approx(foot, abs=1e-5)

    # Exported again, the URDF is the leg it was: joint zeros are the hardware's.
    source = read_urdf(tmp_path / "source" / "rig.urdf")
    exported = read_urdf(_export(ctx, converted, tmp_path / "out"))
    for name, joint in movable(source).items():
        assert_same_joint(name, joint, exported["joints"][name])
