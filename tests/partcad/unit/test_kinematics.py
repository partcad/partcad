#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What becomes a rigid body, and how the joints between bodies move: 'wrappers/kinematics.py'.

The module three exporters share - MJCF and SDFormat in the simulation plugins,
URDF here - so that they cannot come to disagree about which parts of a robot
are one body or how its joints are written. Two halves, tested apart:

* **the classification** of a joint's free steps, row by row of the table in
  section 8.8 of docs/design/simulation.md, on steps written by hand and on the
  steps the core builds for every kind 'motion.type' names; and the frames each
  exporter writes a joint in, checked against the joint's own product;
* **the body rule** of section 7, on trees the core builds from small packages
  of its own - instantiated and composed without any geometry, so none of this
  needs a sandbox - and over every ASSY object under examples/.

Placements are compared exactly wherever the promise is exact (a part's world
placement is its body's times its placement in the body; a scene of parts
sits where an exporter writing every node as a free body put it) and to
rounding where the tree's packed axis-and-angle form cannot carry more (a joint
reproducing its child's placement).
"""

import asyncio
import logging
import math
import os
import random
import shutil
import sys
import textwrap

import pytest

import partcad as pc
from partcad import shape_envelope

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import kinematics  # noqa: E402
import mass_properties  # noqa: E402
import urdf_common  # noqa: E402

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")
EXAMPLES = "examples"

X = (1.0, 0.0, 0.0)
Y = (0.0, 1.0, 0.0)
Z = (0.0, 0.0, 1.0)


def free(kind, axis, lower=None, upper=None, value=0.0, coupling=None):
    """One free step as the tree states it ('partcad.joint.FreeStep.to_envelope')."""
    return {
        "type": "free",
        "kind": kind,
        "axis": list(axis),
        "lower": lower,
        "upper": upper,
        "value": value,
        "source": [{"side": "to", "parameter": "p"}],
        "coupling": coupling,
    }


def fixed(translation=(0, 0, 0), axis=(0, 0, 1), angle=0, role="adjustment"):
    return {"type": "fixed", "role": role, "location": [list(translation), list(axis), angle]}


def _close_pose(a, b, tolerance=1e-9) -> bool:
    """Two poses that are one, to rounding: the quaternion either way round, the translation in mm."""
    (qa, ta), (qb, tb) = a, b
    same = max(abs(x - y) for x, y in zip(qa, qb))
    flipped = max(abs(x + y) for x, y in zip(qa, qb))
    return min(same, flipped) <= tolerance and max(abs(x - y) for x, y in zip(ta, tb)) <= tolerance * 1000


def _close_vector(a, b, tolerance=1e-9) -> bool:
    return max(abs(float(x) - float(y)) for x, y in zip(a, b)) <= tolerance


def _value_sets(joint, count=6, seed=7):
    """The starting values, zero, and a few random configurations within (or near) the bounds."""
    generator = random.Random(seed)
    sets = [None, [0.0] * len(joint.freedoms)]
    for _ in range(count):
        values = []
        for freedom in joint.freedoms:
            low = freedom.lower if freedom.lower is not None else (-170.0 if freedom.kind == kinematics.TURN else -50.0)
            high = freedom.upper if freedom.upper is not None else (170.0 if freedom.kind == kinematics.TURN else 50.0)
            values.append(generator.uniform(low, high))
        sets.append(values)
    return sets


def _check_decomposition(joint):
    """The classification multiplied back out is the joint, wherever it is moved to."""
    classification = joint.classification
    for values in _value_sets(joint):
        assert _close_pose(classification.location(values), joint.location(values)), (classification.kind, values)
    if classification.kind not in (kinematics.CHAIN, kinematics.FIXED):
        # A native joint sits at its origin: every line goes through it.
        assert all(point == (0.0, 0.0, 0.0) for point in classification.points), classification.points


#
# The classification table, row by row (docs/design/simulation.md, 8.8)
#


TABLE = [
    ("none", [fixed((1, 2, 3))], kinematics.FIXED),
    ("one turn, limited", [free("turn", Z, -90, 90)], kinematics.REVOLUTE),
    ("one turn, bounded on one side", [free("turn", Z, None, 90)], kinematics.REVOLUTE),
    ("one turn, unlimited", [free("turn", Z)], kinematics.CONTINUOUS),
    ("one move", [free("move", X, 0, 5)], kinematics.PRISMATIC),
    ("one move, unlimited, along a parameter twice the unit", [free("move", (0, 0, 2))], kinematics.PRISMATIC),
    (
        "turn + move on one axis, coupled",
        [free("turn", Z), free("move", Z, coupling={"step": 0, "ratio": 0.5 / 360.0, "offset": 0.0})],
        kinematics.SCREW,
    ),
    (
        "move + turn on one axis, the turn followed",
        [free("move", (0, 0, -1)), free("turn", Z, coupling={"step": 0, "ratio": 720.0, "offset": 0.0})],
        kinematics.SCREW,
    ),
    ("turn + move on one axis", [free("turn", Z), free("move", (0, 0, -1))], kinematics.CYLINDRICAL),
    (
        "move + turn on one parallel axis, apart from the origin",
        [free("move", Z), fixed((5, 0, 0)), free("turn", Z)],
        kinematics.CYLINDRICAL,
    ),
    ("two turns through a point", [free("turn", Z), free("turn", X)], kinematics.UNIVERSAL),
    (
        "two turns through a point up the first axis",
        [free("turn", Z), fixed((0, 0, 10)), free("turn", X)],
        kinematics.UNIVERSAL,
    ),
    ("three turns through a point", [free("turn", X), free("turn", Y), free("turn", Z)], kinematics.BALL),
    (
        "three turns through a point off the origin",
        [free("turn", Z), fixed((0, 0, 10), (0, 0, 1), 90), free("turn", X), free("turn", Y)],
        kinematics.BALL,
    ),
    ("two moves and the normal turn", [free("move", X), free("move", Y), free("turn", Z)], kinematics.PLANAR),
    (
        "two moves and the normal turn, about a line off the origin",
        [free("move", X), free("move", Y), fixed((3, 4, 0)), free("turn", Z)],
        kinematics.PLANAR,
    ),
    (
        "all six",
        [free("move", X), free("move", Y), free("move", Z), free("turn", X), free("turn", Y), free("turn", Z)],
        kinematics.FLOATING,
    ),
    # Anything else is a chain.
    ("two parallel turns apart", [free("turn", Z), fixed((100, 0, 0)), free("turn", Z)], kinematics.CHAIN),
    ("two turns that pass apart", [free("turn", Z), fixed((10, 0, 0)), free("turn", Y)], kinematics.CHAIN),
    ("a turn and a move across it", [free("turn", Z), free("move", X)], kinematics.CHAIN),
    ("two moves", [free("move", X), free("move", Y)], kinematics.CHAIN),
    ("the turn before the two moves", [free("turn", Z), free("move", X), free("move", Y)], kinematics.CHAIN),
    (
        "three turns not through one point",
        [free("turn", X), free("turn", Y), fixed((5, 0, 0)), free("turn", Z)],
        kinematics.CHAIN,
    ),
    (
        "a coupled pair across each other",
        [free("turn", Z), free("move", X, coupling={"step": 0, "ratio": 0.01, "offset": 0.0})],
        kinematics.CHAIN,
    ),
    (
        "a coupled universal",
        [free("turn", Z), free("turn", X, coupling={"step": 0, "ratio": 1.0, "offset": 0.0})],
        kinematics.CHAIN,
    ),
]


@pytest.mark.parametrize("steps, kind", [(steps, kind) for _, steps, kind in TABLE], ids=[row[0] for row in TABLE])
def test_the_classification_table(steps, kind):
    joint = kinematics.Joint({"name": "j", "steps": steps})
    assert kinematics.classify(joint).kind == kind
    # The same answer from the tree's own spelling, and from the steps alone.
    assert kinematics.classify({"steps": steps}).kind == kind
    assert kinematics.classify(steps).kind == kind
    _check_decomposition(joint)


def test_a_native_joint_is_centred_where_its_lines_meet():
    ball = kinematics.classify([free("turn", Z), fixed((0, 0, 10), (0, 0, 1), 90), free("turn", X), free("turn", Y)])
    assert _close_vector(ball.origin[1], (0, 0, 10))
    universal = kinematics.classify([free("turn", Z), fixed((0, 0, 10)), free("turn", X)])
    assert _close_vector(universal.origin[1], (0, 0, 10))
    planar = kinematics.classify([free("move", X), free("move", Y), fixed((3, 4, 0)), free("turn", Z)])
    assert _close_vector(planar.origin[1], (3, 4, 0))
    cylindrical = kinematics.classify([free("move", Z), fixed((5, 0, 0)), free("turn", Z)])
    assert _close_vector(cylindrical.origin[1], (5, 0, 0))


def test_each_axis_is_stated_in_the_joint_frame():
    # A half turn about X between the two turns makes the second one's +Z the
    # joint frame's -Z: the axis is where it points there, sign and all.
    found = kinematics.classify([free("turn", Z), fixed((0, 0, 0), (1, 0, 0), 180), free("turn", (0, 1, 0))])
    assert _close_vector(found.axes[0], Z)
    assert _close_vector(found.axes[1], (0, -1, 0))
    assert found.kind == kinematics.UNIVERSAL


#
# Units: what an exporter writes is degrees and millimetres along a unit axis
#


def test_a_move_along_a_long_direction_is_millimetres_along_a_unit_axis():
    # The parameter moves 2 mm per unit along +Z, so 3 of it is 6 mm, and its
    # range of 0..5 is 0..10 mm.
    (freedom,) = kinematics.Joint({"steps": [free("move", (0, 0, 2), 0, 5, value=3)]}).freedoms
    assert (freedom.axis, freedom.scale, freedom.value, freedom.lower, freedom.upper) == (Z, 2.0, 6.0, 0.0, 10.0)
    assert freedom.parameter == "p"


def test_a_coupling_is_restated_in_the_units_of_the_two_freedoms():
    # A thread of 0.5 mm a turn, on a parameter that moves 2 mm per unit.
    joint = kinematics.Joint(
        {
            "steps": [
                free("turn", Z, value=90),
                free("move", (0, 0, 2), value=0.125, coupling={"step": 0, "ratio": 0.25 / 360.0, "offset": 0.0625}),
            ]
        }
    )
    turn, move = joint.freedoms
    assert move.follows == turn.index
    assert move.ratio == pytest.approx(0.5 / 360.0)
    assert move.offset == pytest.approx(0.125)
    # Where the connection started them, the relation holds in the new units.
    assert move.value == pytest.approx(move.ratio * turn.value + move.offset)
    assert joint.kind == kinematics.SCREW


def test_an_unlimited_bound_is_none():
    (freedom,) = kinematics.Joint({"steps": [free("turn", Z, None, None)]}).freedoms
    assert (freedom.lower, freedom.upper, freedom.limited) == (None, None, False)


#
# The frames an exporter writes a joint in
#

# A double pendulum: a hinge at the parent's origin, an arm 100 mm along X, a
# second hinge, and the child 20 mm further on.
PENDULUM = [
    fixed((0, 0, 5), role="port"),
    free("turn", Z, -90, 90, value=30),
    fixed((100, 0, 0)),
    free("turn", Z, value=-45),
    fixed((20, 0, 0), role="sourcePort"),
]


def test_the_chain_is_the_fixed_steps_between_the_freedoms():
    joint = kinematics.Joint({"name": "pendulum", "steps": PENDULUM})
    assert joint.kind == kinematics.CHAIN
    assert len(joint.origins) == 2
    assert _close_pose(joint.origin, kinematics.pose_of([[0, 0, 5], [0, 0, 1], 0]))
    assert _close_pose(joint.origins[1], kinematics.pose_of([[100, 0, 0], [0, 0, 1], 0]))
    assert _close_pose(joint.tail, kinematics.pose_of([[20, 0, 0], [0, 0, 1], 0]))
    # URDF's way: a link per freedom, each joint at its origin in the frame the
    # one before it moved, and the child at the tail in the last of them.
    for values in _value_sets(joint):
        pose = kinematics.IDENTITY
        for freedom, origin, value in zip(joint.freedoms, joint.origins, joint.values(values)):
            pose = kinematics.compose(kinematics.compose(pose, origin), freedom.motion(value) or kinematics.IDENTITY)
        assert _close_pose(kinematics.compose(pose, joint.tail), joint.location(values))


def test_each_line_in_the_child_body_is_what_mjcf_moves_the_body_about():
    """MJCF's way: the body at the starting pose, its joints in order, each about its axis in the body.

    Each joint turns or moves the body's frame as the ones before it left it,
    by how far it is from the 'ref' it starts at - which is what MuJoCo does
    with joints listed in one body, and so what step 10 will write.
    """
    joint = kinematics.Joint({"name": "pendulum", "steps": PENDULUM})
    start = joint.values()
    # The second hinge is at the child's origin less 20 mm, the first one
    # further back along the arm, both about +Z of a body turned -15 degrees.
    assert _close_vector(joint.anchor_in_child(1), (-20, 0, 0))
    assert _close_vector(joint.axis_in_child(0), Z) and _close_vector(joint.axis_in_child(1), Z)
    for values in _value_sets(joint):
        values = joint.values(values)
        frame = joint.location()
        for index, freedom in enumerate(joint.freedoms):
            anchor = joint.anchor_in_child(index)
            delta = kinematics.motion(freedom.kind, joint.axis_in_child(index), values[index] - start[index])
            if delta is None:
                continue
            if freedom.kind == kinematics.TURN:
                delta = kinematics.compose(
                    kinematics.compose(kinematics.translation(anchor), delta),
                    kinematics.translation([-v for v in anchor]),
                )
            frame = kinematics.compose(frame, delta)
        assert _close_pose(frame, joint.location(values)), values


def test_each_line_in_the_parent_body():
    joint = kinematics.Joint({"name": "pendulum", "steps": PENDULUM})
    # At zero the second hinge is 100 mm along X from the first, which is 5 mm up.
    zero = [0.0, 0.0]
    assert _close_vector(joint.anchor_in_parent(0, zero), (0, 0, 5))
    assert _close_vector(joint.anchor_in_parent(1, zero), (100, 0, 5))
    # At the starting values the arm is turned 30 degrees, and the hinge with it.
    turned = (100 * math.cos(math.radians(30)), 100 * math.sin(math.radians(30)), 5)
    assert _close_vector(joint.anchor_in_parent(1), turned)
    assert _close_vector(joint.axis_in_parent(1), Z)


def test_a_ball_is_written_at_its_centre_in_the_body_it_moves():
    """An MJCF ball's 'pos': the point all three turns go through, which the turns leave where it is."""
    joint = kinematics.Joint(
        {
            "steps": [
                fixed((0, 0, 5), role="port"),
                free("turn", Z, value=20),
                fixed((0, 0, 10), (0, 0, 1), 90),
                free("turn", X, value=-35),
                free("turn", Y, value=50),
                fixed((30, 0, 0), role="sourcePort"),
            ]
        }
    )
    assert joint.kind == kinematics.BALL
    # 15 mm up in the parent: 5 of port, 10 along the first turn's axis.
    assert _close_vector(joint.classification.origin[1], (0, 0, 15))
    centre = joint.origin_in_child()[1]
    for values in _value_sets(joint):
        in_parent = kinematics.transform_point(joint.location(values), centre)
        assert _close_vector(in_parent, (0, 0, 15)), values
    # And the child's origin is 30 mm from it, as the source port says.
    assert _length(centre) == pytest.approx(30.0)


def _length(vector):
    return math.sqrt(sum(v * v for v in vector))


def test_a_screw_moves_as_its_thread_says():
    joint = kinematics.Joint(
        {"steps": [free("turn", Z), free("move", Z, coupling={"step": 0, "ratio": 1.0 / 360.0, "offset": 0.0})]}
    )
    turn, move = joint.freedoms
    # A full turn advances one lead: the values of a screw are the turn's, the
    # move following by the coupling.
    lead = joint.location([360.0, move.ratio * 360.0 + move.offset])
    assert _close_vector(lead[1], (0, 0, 1))


#
# Real joints: every kind 'motion.type' names, as the core builds it
#

RIG = """
parts:
  base:
    type: stl
    path: cube.stl
    implements:
      bore:
        top: [[0, 0, 10], [0, 0, 1], 0]
  arm:
    type: stl
    path: cube.stl
    implements:
      pin:
  lid:
    type: stl
    path: cube.stl
    implements:
      pin:
      bore:
        top: [[0, 0, 10], [0, 0, 1], 0]
interfaces:
  bore:
    ports:
      hole:
{bore}
  pin:
    ports:
      tip: [[0, 0, 0], [0.71, 0.71, 0], 180]
    mates:
      bore: {{}}
{objects}
"""


def _indented(text, spaces):
    text = textwrap.dedent(text or "").strip("\n")
    return textwrap.indent(text, " " * spaces) if text else ""


def _context(root, files, objects, bore=""):
    """A package of three cubes and two interfaces, with the objects and the ASSY files given."""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(CUBE, root / "cube.stl")
    (root / "partcad.yaml").write_text(RIG.format(bore=_indented(bore, 4), objects=textwrap.dedent(objects)))
    for name, text in files.items():
        (root / name).write_text(textwrap.dedent(text))
    return pc.Context(str(root))


@pytest.fixture
def stand_in_geometry(monkeypatch):
    """Every part a shape of no geometry, and every ASSY object composed as it always is.

    'get_wrapped' is the one call that would build anything, and a part's
    stand-in carries what the core stamps on it (its name, its label, its
    properties) and a payload nothing reads. An assembly or a scene is
    instantiated and composed by its own code, which needs no CAD kernel.
    """

    async def part(self, ctx):
        return dict(self.get_cache_metadata(), brep=b"BREP")

    async def assembly(self, ctx):
        await self.do_instantiate()
        return await self._get_shape_real(ctx)

    monkeypatch.setattr(pc.Part, "get_wrapped", part)
    monkeypatch.setattr(pc.Assembly, "get_wrapped", assembly)


def _tree(ctx, path, kind="assembly", params=None):
    obj = ctx.get_scene(path, params) if kind == "scene" else ctx.get_assembly(path, params)
    assert obj is not None, path
    return asyncio.run(obj.get_wrapped(ctx))


ONE_JOINT = """
links:
  - part: base
  - part: arm
    connect: {{name: base, with: pin, to: bore{params}}}
"""


@pytest.mark.parametrize(
    "bore, kind",
    [
        ("motion: {type: revolute, limits: {lower: 0, upper: 90}}", kinematics.REVOLUTE),
        ("parameters: {turnZ: [-90, 90]}\nmotion: revolute", kinematics.REVOLUTE),
        # A turn nothing bounds is continuous, whatever its declaration called it.
        ("motion: revolute", kinematics.CONTINUOUS),
        ("motion: continuous", kinematics.CONTINUOUS),
        ("motion: {type: prismatic, limits: {lower: 0, upper: 5}}", kinematics.PRISMATIC),
        ("motion: cylindrical", kinematics.CYLINDRICAL),
        ("threadStep: 0.5\nmotion: screw", kinematics.SCREW),
        ("motion: universal", kinematics.UNIVERSAL),
        ("motion: ball", kinematics.BALL),
        ("motion: planar", kinematics.PLANAR),
        ("motion: floating", kinematics.FLOATING),
    ],
)
def test_every_kind_a_motion_names_classifies_as_itself(tmp_path, stand_in_geometry, bore, kind):
    ctx = _context(tmp_path, {"rig.assy": ONE_JOINT.format(params="")}, "assemblies:\n  rig: {type: assy}\n", bore=bore)
    tree = _tree(ctx, ":rig")
    found = kinematics.bodies(tree)
    assert [body.name for body in found] == ["rig", "arm"]
    arm = found.by_name("arm")
    assert arm.joint.kind == kind
    # And the kind of the node's joint as the tree states it, before any body
    # was found for it, is the same.
    node = tree[shape_envelope.KEY_ASSEMBLY][1]
    assert kinematics.classify(node[shape_envelope.KEY_JOINT]).kind == kind
    _check_decomposition(arm.joint)
    assert _close_pose(kinematics.compose(arm.parent.world, arm.joint.location()), arm.world)


@pytest.mark.parametrize(
    "bore, params",
    [
        ("parameters: {turnZ: [-90, 90]}\nmotion: revolute", ", toParams: {turnZ: 30}"),
        (
            "parameters: {turnZ: [-90, 90], moveX: [-5, 5]}\nmotion: {dof: [turnZ]}",
            ", toParams: {moveX: 2, turnZ: -20}",
        ),
        ("motion: ball", ""),
        ("motion: {type: prismatic, limits: {lower: 0, upper: 5}}", ", withParams: {moveZ: 3}"),
    ],
)
def test_the_starting_values_put_the_child_where_the_assembly_shows_it(tmp_path, stand_in_geometry, bore, params):
    """#766's invariant on the body pair: the product of the steps at their values is the placement."""
    ctx = _context(
        tmp_path, {"rig.assy": ONE_JOINT.format(params=params)}, "assemblies:\n  rig: {type: assy}\n", bore=bore
    )
    found = kinematics.bodies(_tree(ctx, ":rig"))
    arm = found.by_name("arm")
    assert _close_pose(kinematics.compose(arm.parent.world, arm.joint.location()), arm.world)


#
# The body rule (docs/design/simulation.md, section 7)
#

PARTS_AND_SCENES = """
assemblies:
  rig:
    type: assy
    path: rig.assy
scenes:
  pile:
    type: assy
    path: pile.assy
  room:
    type: assy
    path: room.assy
"""

PILE = """
links:
  - part: base
    name: bottom
    location: [[0, 0, 0], [0, 0, 1], 0]
  - part: base
    name: top
    location: [[3, 0, 20], [0, 0, 1], 15]
"""

RIG_ASSY = """
links:
  - part: base
  - part: lid
    location: [[0, 30, 0], [1, 0, 0], 90]
  - part: arm
    connect: {name: base, with: pin, to: bore, toParams: {turnZ: 30}}
"""


def _flat_poses(tree):
    """Where an exporter writing every node with geometry as a free body puts each one.

    The 'flatten: true' walk the engine plugins' exporters make today (see
    'emit_flat' in partcad-sim-mujoco), composed the way they compose it.
    """
    poses = {}

    def walk(node, pose):
        if kinematics.is_geometry(node):
            poses[id(node)] = pose
        for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
            walk(child, urdf_common.compose(pose, urdf_common.from_packed(child.get(shape_envelope.KEY_LOCATION))))

    root_pose = urdf_common.from_packed(tree.get(shape_envelope.KEY_LOCATION))
    if kinematics.is_geometry(tree):
        walk(tree, root_pose)
    for child in tree.get(shape_envelope.KEY_ASSEMBLY) or []:
        walk(child, urdf_common.compose(root_pose, urdf_common.from_packed(child.get(shape_envelope.KEY_LOCATION))))
    return poses


def _assert_placements(found, tree):
    """Every invariant a body's placements keep, over one tree."""
    flat = _flat_poses(tree)
    for body in found:
        for part in body.parts:
            # By definition, and so exactly.
            assert part.world == kinematics.compose(body.world, part.placement)
            # And where the tree says the part is, to rounding - to the bit for
            # the node the body is rooted at, which is where an exporter that
            # made every node a body of its own put it.
            assert _close_pose(part.world, flat[id(part.node)]), (body.name, part.label)
            if part.node is body.node:
                assert part.world == flat[id(part.node)], (body.name, part.label)
        if body.joint is not None:
            assert isinstance(body.parent, kinematics.Body)
            assert _close_pose(kinematics.compose(body.parent.world, body.joint.location()), body.world), body.name


def test_every_element_of_a_scene_is_a_body_of_its_own(tmp_path, stand_in_geometry):
    ctx = _context(tmp_path, {"pile.assy": PILE}, PARTS_AND_SCENES)
    tree = _tree(ctx, ":pile", "scene")
    found = kinematics.bodies(tree)
    assert kinematics.summary(found) == [
        {"name": "bottom", "kind": "part", "parent": None, "fixed": False, "parts": ["bottom"]},
        {"name": "top", "kind": "part", "parent": None, "fixed": False, "parts": ["top"]},
    ]
    assert found.problems == []
    _assert_placements(found, tree)


def test_a_scene_connects_without_attaching(tmp_path, stand_in_geometry):
    """A 'connect:' in a scene places one object against another; nothing moves against anything."""
    files = {"pile.assy": ONE_JOINT.format(params=", toParams: {turnZ: 30}")}
    ctx = _context(tmp_path, files, PARTS_AND_SCENES, bore="parameters: {turnZ: [-90, 90]}\nmotion: revolute")
    tree = _tree(ctx, ":pile", "scene")
    found = kinematics.bodies(tree)
    assert [(body.name, body.parent, body.joint) for body in found] == [("base", None, None), ("arm", None, None)]
    _assert_placements(found, tree)


def test_a_scene_placed_in_a_scene_has_bodies_of_its_own_recursively(tmp_path, stand_in_geometry):
    room = """
    links:
      - scene: pile
        name: stack
        location: [[100, 0, 0], [0, 0, 1], 0]
      - part: lid
        location: [[0, 0, 50], [0, 0, 1], 0]
    """
    ctx = _context(tmp_path, {"pile.assy": PILE, "room.assy": room}, PARTS_AND_SCENES)
    tree = _tree(ctx, ":room", "scene")
    found = kinematics.bodies(tree)
    assert [(body.name, body.path, body.parent) for body in found] == [
        ("bottom", ("stack", "bottom"), None),
        ("top", ("stack", "top"), None),
        ("lid", ("lid",), None),
    ]
    _assert_placements(found, tree)


def test_a_links_list_inside_a_scene_holds_elements_of_the_scene(tmp_path, stand_in_geometry):
    room = """
    links:
      - name: shelf
        location: [[0, 0, 100], [0, 0, 1], 0]
        links:
          - part: base
          - part: lid
            location: [[30, 0, 0], [0, 0, 1], 0]
    """
    ctx = _context(tmp_path, {"room.assy": room}, PARTS_AND_SCENES)
    tree = _tree(ctx, ":room", "scene")
    assert tree[shape_envelope.KEY_ASSEMBLY][0][shape_envelope.KEY_KIND] == "scene"
    found = kinematics.bodies(tree)
    assert [body.name for body in found] == ["base", "lid"]
    _assert_placements(found, tree)


def test_everything_in_an_assembly_is_one_body_of_combined_physics(tmp_path, stand_in_geometry):
    rigid = """
    links:
      - part: base
      - part: lid
        location: [[0, 30, 0], [1, 0, 0], 90]
      - part: arm
        connect: {name: base, with: pin, to: bore}
    """
    ctx = _context(tmp_path, {"rig.assy": rigid}, PARTS_AND_SCENES)
    tree = _tree(ctx, ":rig")
    names = {node["label"]: node["name"] for node in tree[shape_envelope.KEY_ASSEMBLY]}
    cube = {"mass": 2.0, "centerOfMass": [1.0, 2.0, 3.0], "inertia": {"ixx": 0.1, "iyy": 0.2, "izz": 0.3}}
    properties = {
        names["base"]: {"physics": dict(cube)},
        names["lid"]: {"physics": dict(cube, mass=1.0)},
        names["arm"]: {"physics": dict(cube, mass=0.5)},
    }
    (body,) = kinematics.bodies(tree, properties)
    assert (body.name, body.kind, body.parent, body.joint) == ("rig", "assembly", None, None)
    assert [part.label for part in body.parts] == ["base", "lid", "arm"]
    # Combined as the one copy of that arithmetic combines it: each part where
    # the body holds it, the parallel-axis theorem between them.
    expected = mass_properties.combined(
        [mass_properties.placed(part.physics, kinematics.packed_of(part.placement)) for part in body.parts]
    )
    assert body.physics["mass"] == pytest.approx(3.5)
    assert body.physics["centerOfMass"] == pytest.approx(expected["centerOfMass"])
    for key in mass_properties.INERTIA_KEYS:
        assert body.physics["inertia"][key] == pytest.approx(expected["inertia"][key])
    _assert_placements([body], tree)


def test_a_connection_that_keeps_a_freedom_is_a_joint_to_the_body_of_its_target(tmp_path, stand_in_geometry):
    ctx = _context(
        tmp_path, {"rig.assy": RIG_ASSY}, PARTS_AND_SCENES, bore="parameters: {turnZ: [-90, 90]}\nmotion: revolute"
    )
    tree = _tree(ctx, ":rig")
    found = kinematics.bodies(tree)
    rig, arm = found
    assert [part.label for part in rig.parts] == ["base", "lid"]
    assert (arm.parent, arm.joint.name, arm.joint.kind, arm.joint.parent, arm.joint.child) == (
        rig,
        "arm-base",
        kinematics.REVOLUTE,
        rig,
        arm,
    )
    assert rig.children == [arm]
    (freedom,) = arm.joint.freedoms
    assert (freedom.lower, freedom.upper, freedom.value) == (-90.0, 90.0, 30.0)
    _assert_placements(found, tree)


def test_an_assembly_in_a_scene_is_one_articulated_tree_whose_root_is_free(tmp_path, stand_in_geometry):
    room = """
    links:
      - assembly: rig
        name: robot
        location: [[0, 100, 0], [0, 0, 1], 90]
      - scene: pile
    """
    ctx = _context(
        tmp_path,
        {"rig.assy": RIG_ASSY, "pile.assy": PILE, "room.assy": room},
        PARTS_AND_SCENES,
        bore="parameters: {turnZ: [-90, 90]}\nmotion: revolute",
    )
    tree = _tree(ctx, ":room", "scene")
    found = kinematics.bodies(tree)
    assert [(row["name"], row["parent"], row["fixed"]) for row in kinematics.summary(found)] == [
        ("robot", None, False),
        ("arm", "robot", False),
        ("bottom", None, False),
        ("top", None, False),
    ]
    assert found.by_name("robot").is_root and not found.by_name("arm").is_root
    _assert_placements(found, tree)


def test_fixed_welds_what_a_scene_places_to_the_world(tmp_path, stand_in_geometry):
    room = """
    links:
      - part: lid
        name: table
        fixed: true
      - assembly: rig
        name: robot
        fixed: true
        location: [[0, 100, 0], [0, 0, 1], 0]
      - scene: pile
        name: bolted
        fixed: true
        location: [[100, 0, 0], [0, 0, 1], 0]
      - part: lid
        name: loose
        location: [[0, 0, 100], [0, 0, 1], 0]
    """
    ctx = _context(
        tmp_path,
        {"rig.assy": RIG_ASSY, "pile.assy": PILE, "room.assy": room},
        PARTS_AND_SCENES,
        bore="parameters: {turnZ: [-90, 90]}\nmotion: revolute",
    )
    tree = _tree(ctx, ":room", "scene")
    found = kinematics.bodies(tree)
    assert [(row["name"], row["parent"], row["fixed"]) for row in kinematics.summary(found)] == [
        ("table", "world", True),
        # A robot bolted to the floor: its root is welded, and its arm still swings.
        ("robot", "world", True),
        ("arm", "robot", False),
        # Fixing a scene fixes every element of it.
        ("bottom", "world", True),
        ("top", "world", True),
        ("loose", None, False),
    ]
    _assert_placements(found, tree)


def test_fixed_is_said_only_where_it_is_true(tmp_path, stand_in_geometry):
    room = """
    links:
      - part: lid
        name: table
        fixed: true
      - part: lid
        name: loose
        fixed: false
    """
    ctx = _context(tmp_path, {"room.assy": room}, PARTS_AND_SCENES)
    table, loose = _tree(ctx, ":room", "scene")[shape_envelope.KEY_ASSEMBLY]
    assert table[shape_envelope.KEY_FIXED] is True
    assert shape_envelope.KEY_FIXED not in loose


def test_nested_sub_assemblies_are_attached_through_and_jointed_where_they_move(tmp_path, stand_in_geometry):
    outer = """
    links:
      - part: lid
        name: frame
      - assembly: rig
        name: left
        location: [[50, 0, 0], [0, 0, 1], 0]
      - name: group
        location: [[0, 50, 0], [0, 0, 1], 0]
        links:
          - part: base
            name: post
          - part: arm
            connect: {name: post, with: pin, to: bore, toParams: {turnZ: -10}}
    """
    objects = PARTS_AND_SCENES.replace("scenes:", "  outer:\n    type: assy\n    path: outer.assy\nscenes:", 1)
    ctx = _context(
        tmp_path,
        {"rig.assy": RIG_ASSY, "outer.assy": outer, "pile.assy": PILE, "room.assy": "links: []\n"},
        objects,
        bore="parameters: {turnZ: [-90, 90]}\nmotion: revolute",
    )
    tree = _tree(ctx, ":outer")
    found = kinematics.bodies(tree)
    assert [(row["name"], row["parent"], row["parts"]) for row in kinematics.summary(found)] == [
        # Everything placed rigidly, however deep, is the outer assembly's body.
        ("outer", None, ["frame", "base", "lid", "post"]),
        # Each arm moves against what it is connected to, which is in that body.
        ("arm", "outer", ["arm"]),
        ("arm-2", "outer", ["arm"]),
    ]
    first, second = found[1], found[2]
    assert (first.path, first.joint.name) == (("left", "arm"), "arm-base")
    assert (second.path, second.joint.name) == (("group", "arm"), "arm-post")
    # The joint starts from where the node it is connected to sits in the
    # parent body: a step of its own, in front of the node's.
    assert first.joint.steps[0].role == kinematics.ROLE_PARENT_FRAME
    _assert_placements(found, tree)


def test_an_assembly_that_states_what_it_weighs_is_taken_at_its_word(tmp_path, stand_in_geometry):
    """A measured link of several shapes - a robot description's - beats the sum of its pieces."""
    outer = """
    links:
      - part: lid
        name: frame
      - assembly: rig
        name: link
        location: [[50, 0, 0], [0, 0, 1], 0]
    """
    rigid = """
    links:
      - part: base
      - part: lid
        location: [[0, 30, 0], [0, 0, 1], 0]
    """
    objects = PARTS_AND_SCENES.replace("scenes:", "  outer:\n    type: assy\n    path: outer.assy\nscenes:", 1)
    ctx = _context(
        tmp_path,
        {"rig.assy": rigid, "outer.assy": outer, "pile.assy": PILE, "room.assy": "links: []\n"},
        objects,
    )
    tree = _tree(ctx, ":outer")
    frame, link = tree[shape_envelope.KEY_ASSEMBLY]
    base, lid = link[shape_envelope.KEY_ASSEMBLY]
    piece = {"mass": 1.0, "centerOfMass": [0.0, 0.0, 0.0], "inertia": {"ixx": 0.01, "iyy": 0.01, "izz": 0.01}}
    properties = {
        frame["name"]: {"physics": dict(piece)},
        base["name"]: {"physics": dict(piece)},
        link["name"]: {"physics": {"mass": 5.0}},
    }
    # 'lid' and 'frame' are the same part: one entry for both, as the index has.
    (body,) = kinematics.bodies(tree, properties)
    # The frame, and the link at the 5 kg it states - not the 2 kg of its pieces.
    assert body.physics["mass"] == pytest.approx(6.0)
    assert len(body.mass_parts()) == 2


def test_a_mechanism_that_states_its_mass_is_weighed_by_its_bodies_and_says_so(tmp_path, stand_in_geometry):
    ctx = _context(tmp_path, {"rig.assy": RIG_ASSY}, PARTS_AND_SCENES, bore="motion: revolute")
    tree = _tree(ctx, ":rig")
    found = kinematics.bodies(tree, {tree["name"]: {"physics": {"mass": 9.0}}})
    assert [body.physics for body in found] == [None, None]
    assert any("states its own mass, and moves" in problem for problem in found.problems)


def test_a_body_name_is_unique_the_way_a_joint_name_is():
    leg = {"name": "pkg:leg", "label": "leg", "kind": "part", "brep": b"x"}
    tree = {"name": "pkg:table", "label": "table", "kind": "scene", "assembly": [dict(leg), dict(leg), dict(leg)]}
    assert [body.name for body in kinematics.bodies(tree)] == ["leg", "leg-2", "leg-3"]


def test_a_part_on_its_own_is_one_free_body():
    found = kinematics.bodies({"name": "pkg:block", "label": "block", "brep": b"x"})
    assert kinematics.summary(found) == [
        {"name": "block", "kind": "part", "parent": None, "fixed": False, "parts": ["block"]}
    ]


def test_a_link_of_several_shapes_is_one_body_wherever_it_is():
    """The slash convention every reader and writer of a robot description keeps."""
    wrist = {
        "name": "pkg:robot/wrist",
        "label": "wrist",
        "kind": "scene",
        "assembly": [
            {"name": "pkg:robot/wrist/1", "label": "wrist/1", "brep": b"x"},
            {"name": "pkg:robot/wrist/2", "label": "wrist/2", "brep": b"y", "location": [[0, 0, 5], [0, 0, 1], 0]},
        ],
    }
    found = kinematics.bodies({"name": "pkg:world", "label": "world", "kind": "scene", "assembly": [wrist]})
    assert kinematics.summary(found) == [
        {"name": "wrist", "kind": "scene", "parent": None, "fixed": False, "parts": ["wrist/1", "wrist/2"]}
    ]


def test_a_tree_written_before_kinds_is_read_by_what_it_carries():
    """No 'kind' anywhere: children make an assembly, geometry a part - one body, as a product."""
    tree = {
        "name": "pkg:stack",
        "label": "stack",
        "assembly": [
            {"name": "pkg:block", "label": "bottom", "brep": b"x"},
            {"name": "pkg:block", "label": "top", "brep": b"x", "location": [[0, 0, 20], [0, 0, 1], 0]},
        ],
    }
    assert [body.name for body in kinematics.bodies(tree)] == ["stack"]


def test_what_the_rule_sets_aside_is_said():
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "kind": "assembly",
        "assembly": [{"name": "pkg:block", "label": "bolted", "kind": "part", "fixed": True, "brep": b"x"}],
    }
    found = kinematics.bodies(tree)
    assert [body.name for body in found] == ["rig"]
    assert any("'bolted' is marked 'fixed'" in problem for problem in found.problems)
    with pytest.raises(ValueError):
        kinematics.bodies({"name": "not a tree"})


#
# What the core stamps on the tree for the rule
#


def test_every_placed_node_says_what_it_holds(tmp_path, stand_in_geometry):
    room = """
    links:
      - scene: pile
      - assembly: rig
      - part: lid
    """
    ctx = _context(tmp_path, {"rig.assy": RIG_ASSY, "pile.assy": PILE, "room.assy": room}, PARTS_AND_SCENES)
    tree = _tree(ctx, ":room", "scene")
    assert tree[shape_envelope.KEY_KIND] == "scene"
    pile, rig, lid = tree[shape_envelope.KEY_ASSEMBLY]
    assert [node[shape_envelope.KEY_KIND] for node in (pile, rig, lid)] == ["scene", "assembly", "part"]
    assert [node[shape_envelope.KEY_KIND] for node in rig[shape_envelope.KEY_ASSEMBLY]] == ["part"] * 3
    # Plain data, so it survives the codec every hop uses.
    assert shape_envelope.loads(shape_envelope.dumps(tree))[shape_envelope.KEY_ASSEMBLY][0]["kind"] == "scene"


def test_an_assembly_refuses_to_place_a_scene(tmp_path, stand_in_geometry, caplog):
    rig = """
    links:
      - part: base
      - scene: pile
        name: heap
    """
    ctx = _context(tmp_path, {"rig.assy": rig, "pile.assy": PILE}, PARTS_AND_SCENES)
    with caplog.at_level(logging.ERROR):
        tree = _tree(ctx, ":rig")
    assert [node["label"] for node in tree[shape_envelope.KEY_ASSEMBLY]] == ["base"]
    assert any("an assembly cannot hold a scene" in record.getMessage() for record in caplog.records)


def test_an_assembly_says_fixed_means_nothing_inside_it(tmp_path, stand_in_geometry, caplog):
    rig = """
    links:
      - part: base
        fixed: true
      - part: lid
        fixed: "yes"
    """
    ctx = _context(tmp_path, {"rig.assy": rig}, PARTS_AND_SCENES)
    with caplog.at_level(logging.ERROR):
        tree = _tree(ctx, ":rig")
    assert all(shape_envelope.KEY_FIXED not in node for node in tree[shape_envelope.KEY_ASSEMBLY])
    messages = [record.getMessage() for record in caplog.records]
    assert any("only a scene fixes what it places" in message for message in messages)
    assert any("'fixed' must be true or false" in message for message in messages)


def test_the_root_of_a_scene_file_has_nothing_to_be_fixed_to(tmp_path, stand_in_geometry, caplog):
    room = """
    fixed: true
    links:
      - part: lid
    """
    ctx = _context(tmp_path, {"room.assy": room}, PARTS_AND_SCENES)
    with caplog.at_level(logging.ERROR):
        tree = _tree(ctx, ":room", "scene")
    assert shape_envelope.KEY_FIXED not in tree[shape_envelope.KEY_ASSEMBLY][0]
    assert any("has nothing to be 'fixed' to" in record.getMessage() for record in caplog.records)


def test_a_scene_file_that_is_one_part_is_not_fixed_by_its_root_either(tmp_path, stand_in_geometry, caplog):
    """A file that is one node and no 'links:' is still the whole scene, and its root says nothing of the world."""
    ctx = _context(tmp_path, {"room.assy": "part: lid\nfixed: true\n"}, PARTS_AND_SCENES)
    with caplog.at_level(logging.ERROR):
        tree = _tree(ctx, ":room", "scene")
    (lid,) = tree[shape_envelope.KEY_ASSEMBLY]
    assert shape_envelope.KEY_FIXED not in lid
    assert any("has nothing to be 'fixed' to" in record.getMessage() for record in caplog.records)
    assert [body.parent for body in kinematics.bodies(tree)] == [None]


def test_a_scene_link_is_keyed_and_staged_like_an_assembly_link(tmp_path):
    room = """
    links:
      - scene: pile
      - part: lid
    """
    ctx = _context(tmp_path, {"pile.assy": PILE, "room.assy": room}, PARTS_AND_SCENES)
    scene = ctx.get_scene(":room")
    sub = asyncio.run(scene.get_subassemblies_async())
    assert [(item.kind, item.name) for item in sub] == [("scene", "pile")]
    # Editing what the placed scene is made of changes the key of what places it.
    before = asyncio.run(scene.get_cache_key_async())
    (tmp_path / "pile.assy").write_text(textwrap.dedent(PILE).replace("15", "25"))
    after = asyncio.run(_context(tmp_path, {}, PARTS_AND_SCENES).get_scene(":room").get_cache_key_async())
    assert before and after and before != after


#
# Every example
#


def _example_packages():
    for directory, subdirectories, files in os.walk(EXAMPLES):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
        if "partcad.yaml" in files and os.path.abspath(directory) != os.path.abspath(EXAMPLES):
            yield "//" + os.path.relpath(directory, EXAMPLES).replace(os.sep, "/")


def test_every_example_keeps_every_placement_invariant(stand_in_geometry):
    ctx = pc.init(EXAMPLES)
    trees = 0
    bodies = 0
    for package in _example_packages():
        project = ctx.get_project(package)
        for kind in ("assembly", "scene"):
            for name, config in sorted(project.object_configs(kind).items()):
                if not isinstance(config, dict) or config.get("type") != "assy":
                    continue
                tree = _tree(ctx, "%s:%s" % (package, name), kind)
                found = kinematics.bodies(tree)
                assert found.problems == [], (package, name)
                _assert_placements(found, tree)
                trees += 1
                bodies += len(found)
    # Not vacuous: there are a score of them, and the scenes hold several bodies.
    assert trees > 15
    assert bodies > trees


def test_the_simulated_stacks_are_where_every_body_was_free_before(stand_in_geometry):
    """The examples' stacks, in the worlds 'pc sim' places them in: bodies, to the bit, where they were.

    What makes the scene rule change nothing for them: every block was a free
    body of its own before ('flatten: true'), and as an element of a scene it
    is one now - at the same world placement, composed the same way.
    """
    ctx = pc.init(EXAMPLES)
    package = "//feature_simulate"
    for name, world in (("stable", ":tilted"), ("unstable", "//builtin/scene:subject"), ("slippery", ":tilted")):
        scene_package, scene_name = pc.utils.resolve_resource_path(package, world)
        params = {"subject": "%s:%s" % (package, name), "subject_kind": "scene", "subject_offset": "0 0 10 0 0 1 0"}
        tree = _tree(ctx, "%s:%s" % (scene_package, scene_name), "scene", params)
        found = kinematics.bodies(tree)
        flat = _flat_poses(tree)
        assert [body.name for body in found] == ["bottom", "top"], name
        assert len(flat) == 2
        for body in found:
            (part,) = body.parts
            assert body.parent is None and body.world == flat[id(part.node)]
