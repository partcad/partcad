#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Joints: the degrees of freedom a connection keeps, and the steps it is made of.

Every test here builds a small package of its own and instantiates an assembly
of it, which reads the declarations and nothing else: no geometry is built,
so none of this needs a sandbox. What the steps compose to is compared with
the placement bit for bit ('_same'), because that is the promise - the joint
*is* the placement, kept as its factors.
"""

import asyncio
import os
import shutil
import textwrap

import pytest

import partcad as pc
from partcad import joint as pc_joint
from partcad import shape_envelope
from partcad.geom import Location

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")

# A base with one bore on top of it, an arm with one pin, and the interfaces.
# 'BORE' and 'PIN' are what each test varies.
PACKAGE = """
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
      bore:{mating}
{pin}
{interfaces}
assemblies:
  rig:
    type: assy
    path: rig.assy
scenes:
  table:
    type: assy
    path: rig.assy
"""


def _indented(text, spaces):
    text = textwrap.dedent(text or "").strip("\n")
    return textwrap.indent(text, " " * spaces) if text else ""


def _package(root, links, bore="", pin="", mating="", interfaces=""):
    """The package above, with the interfaces and the ASSY file given, written into 'root'."""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(CUBE, root / "cube.stl")
    mating_text = ("\n" + _indented(mating, 8)) if mating else " {}"
    (root / "partcad.yaml").write_text(
        PACKAGE.format(
            bore=_indented(bore, 4),
            pin=_indented(pin, 4),
            mating=mating_text,
            interfaces=_indented(interfaces, 2),
        )
    )
    (root / "rig.assy").write_text(textwrap.dedent(links))
    return pc.Context(str(root))


def _rig(root, links, **declarations):
    """The package above, and its assembly instantiated."""
    assembly = _package(root, links, **declarations)._get_assembly(":rig")
    asyncio.run(assembly.do_instantiate())
    return assembly


def _child(assembly, name):
    return next(child for child in assembly.children if child.name == name)


def _same(a: Location, b: Location) -> bool:
    return a._q == b._q and a._t == b._t


LINKS = """
links:
  - part: base
  - part: arm
    connect:
      name: base
      with: pin
      to: bore
      {extra}
"""


def _links(extra=""):
    return LINKS.format(extra=extra)


#
# What is free
#


def test_a_connection_with_no_motion_is_a_rigid_attachment(tmp_path):
    assembly = _rig(tmp_path, _links("toParams: {turnZ: 30}"), bore="parameters: {turnZ: [-90, 90]}")
    arm = _child(assembly, "arm")
    # There are no fixed joints: an adjustment is a fixed step and nothing more.
    assert arm.joint is None
    assert [step.role for step in arm.composition.steps] == ["port", "facing", "adjustment", "sourcePort"]
    assert _same(arm.composition.location(), arm.location)
    assert list(assembly.joints()) == []


def test_dof_names_the_parameters_that_stay_free(tmp_path):
    bore = """
        parameters:
          turnZ: [-150, 150, 0]
          moveX: [-2, 2]
        motion:
          dof: [turnZ]
        physics:
          damping: 0.05
          maxEffort: 2.0
    """
    assembly = _rig(tmp_path, _links("toParams: {moveX: 1, turnZ: 30}"), bore=bore)
    arm = _child(assembly, "arm")
    joint = arm.joint
    assert joint.name == "arm-base" and (joint.parent, joint.child) == ("base", "arm")
    (free,) = joint.free_steps()
    assert (free.kind, free.axis, free.lower, free.upper, free.value) == ("turn", [0.0, 0.0, 1.0], -150, 150, 30.0)
    assert free.source[0]["parameter"] == "turnZ" and free.source[0]["side"] == "to"
    # 'moveX' is named and not free: an adjustment, fixed at its value, in the
    # order the connection names the two - which is the placement's order.
    assert [step.role if not step.free else "free" for step in joint.steps] == [
        "port",
        "facing",
        "adjustment",
        "free",
        "sourcePort",
    ]
    assert joint.physics == {"damping": 0.05, "maxEffort": 2.0}
    assert _same(joint.composition.location(), arm.location)
    assert arm.joint_problems == []


def test_a_kind_of_joint_implies_its_freedoms_and_brings_the_parameter_it_needs(tmp_path):
    bore = """
        motion:
          type: revolute
          limits: {lower: 0, upper: 90}
    """
    rest = _rig(tmp_path / "rest", _links(), bore=bore)
    (free,) = _child(rest, "arm").joint.free_steps()
    # About the port's Z axis, which is the contact frame's -Z on the target:
    # the implied 'turnZ' turns about +Z, so its range is the limits reversed.
    assert (free.kind, free.axis) == ("turn", [0.0, 0.0, 1.0])
    assert (free.lower, free.upper) == (-90.0, 0.0)
    assert free.source[0]["synthesized"] and free.source[0]["parameter"] == "turnZ"

    # And 'toParams' can address it, though nobody declared it.
    posed = _rig(tmp_path / "posed", _links("toParams: {turnZ: -30}"), bore=bore)
    arm = _child(posed, "arm")
    assert arm.joint.free_steps()[0].value == -30.0
    assert not _same(arm.location, _child(rest, "arm").location)
    # Moving the joint at rest to -30 is where the posed assembly put the arm.
    rest_arm = _child(rest, "arm")
    index = rest_arm.composition.steps.index(rest_arm.joint.free_steps()[0])
    assert _same(rest_arm.composition.location({index: -30.0}), arm.location)


def test_an_implied_freedom_uses_the_declared_parameter_along_its_axis(tmp_path):
    bore = """
        parameters:
          swing: {type: turn, dir: [0, 0, -1], min: -45, max: 45}
        motion: revolute
    """
    assembly = _rig(tmp_path, _links("toParams: {swing: 10}"), bore=bore)
    (free,) = _child(assembly, "arm").joint.free_steps()
    # The port's Z is the contact frame's -Z, which is exactly 'swing'.
    assert free.source[0]["parameter"] == "swing" and not free.source[0]["synthesized"]
    assert (free.lower, free.upper, free.value) == (-45, 45, 10.0)


def test_continuous_is_unlimited_whatever_its_parameter_says(tmp_path):
    bore = """
        parameters:
          angle: {type: turn, dir: [0, 0, -1], min: -360, max: 360}
        motion: continuous
    """
    (free,) = _child(_rig(tmp_path, _links(), bore=bore), "arm").joint.free_steps()
    assert (free.lower, free.upper) == (None, None)


def test_a_source_interface_states_its_axis_in_its_own_port_frame(tmp_path):
    # The connected object's port is the contact frame at zero, so its Z is +Z.
    pin = """
        motion:
          type: prismatic
          limits: {lower: 0, upper: 5}
    """
    (free,) = _child(_rig(tmp_path, _links(), pin=pin), "arm").joint.free_steps()
    assert (free.kind, free.axis, free.lower, free.upper) == ("move", [0.0, 0.0, 1.0], 0.0, 5.0)
    assert free.side == "with"


def test_two_freedoms_on_one_axis_are_one_and_their_ranges_add(tmp_path):
    bore = """
        parameters: {turnZ: [-90, 90]}
        motion: {dof: [turnZ]}
    """
    pin = """
        parameters: {turnZ: [-90, 90]}
        motion: {dof: [turnZ]}
    """
    assembly = _rig(tmp_path, _links("toParams: {turnZ: 20}\n      withParams: {turnZ: 15}"), bore=bore, pin=pin)
    arm = _child(assembly, "arm")
    (free,) = arm.joint.free_steps()
    assert (free.lower, free.upper, free.value) == (-180, 180, 35.0)
    assert {entry["side"] for entry in free.source} == {"to", "with"}
    # Summing two non-zero values is the one case that re-rounds; the joint is
    # still where the placement put the arm, as its own product says.
    assert _same(arm.composition.location(), arm.location)


def test_a_value_on_one_side_of_a_merged_freedom_keeps_the_placement_exact(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    pin = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    adjustments = "parameters: {turnZ: [-90, 90]}"
    plain = _rig(tmp_path / "plain", _links("withParams: {turnZ: 15}"), bore=adjustments, pin=adjustments)
    merged = _rig(tmp_path / "merged", _links("withParams: {turnZ: 15}"), bore=bore, pin=pin)
    # The merged freedom stays where the value was, so the factors are the ones
    # the placement composed without any joint at all.
    assert _same(_child(merged, "arm").location, _child(plain, "arm").location)
    (free,) = _child(merged, "arm").joint.free_steps()
    assert free.side == "with" and free.value == 15.0


def test_antiparallel_freedoms_merge_with_the_sign_of_one_flipped(tmp_path):
    bore = """
        parameters:
          down: {type: move, dir: [0, 0, -1], min: 0, max: 3}
        motion: {dof: [down]}
    """
    pin = "parameters: {moveZ: [0, 2]}\nmotion: {dof: [moveZ]}"
    (free,) = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint.free_steps()
    # 'down' is the kept sense: 0..3 of it, and moveZ 0..2 is -2..0 of it.
    assert (free.axis, free.lower, free.upper) == ([0.0, 0.0, -1.0], -2.0, 3.0)


def test_an_unlimited_freedom_stays_unlimited_when_summed(tmp_path):
    bore = "motion: continuous"
    pin = "parameters: {turnZ: [-10, 10]}\nmotion: {dof: [turnZ]}"
    (free,) = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint.free_steps()
    assert (free.lower, free.upper) == (None, None)


def test_freedoms_on_different_axes_are_kept_apart(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    pin = "parameters: {moveX: [0, 4]}\nmotion: {dof: [moveX]}"
    steps = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint.free_steps()
    assert [(step.kind, step.axis) for step in steps] == [("turn", [0.0, 0.0, 1.0]), ("move", [1.0, 0.0, 0.0])]


def test_a_move_between_two_parallel_turns_keeps_them_apart(tmp_path):
    # Turn, slide, turn: once the slide moves, the two turns are about two lines.
    bore = "parameters: {turnZ: [-90, 90], moveX: [0, 10]}\nmotion: {dof: [turnZ, moveX]}"
    pin = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    steps = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint.free_steps()
    assert [step.kind for step in steps] == ["turn", "move", "turn"]


def test_a_screw_couples_its_move_to_its_turn_by_the_thread(tmp_path):
    bore = "threadStep: 0.5\nmotion: screw"
    joint = _child(_rig(tmp_path, _links(), bore=bore), "arm").joint
    turn, move = joint.free_steps()
    assert (turn.kind, move.kind) == ("turn", "move")
    assert move.follows is turn
    # Both about the port's Z, which is the contact -Z, so both parameters are
    # reversed and the ratio between them is the pitch itself: 0.5 mm a turn.
    assert move.ratio == pytest.approx(0.5 / 360.0)
    assert move.coupling(joint.steps)["step"] == joint.steps.index(turn)
    assert joint.problems == []


def test_a_screw_s_move_is_not_summed_with_a_move_along_its_axis(tmp_path):
    # It follows the turn rather than being a freedom of its own.
    bore = "threadStep: 0.5\nmotion: screw"
    pin = "motion: {type: prismatic, limits: {lower: 0, upper: 5}}"
    joint = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint
    assert [(step.kind, step.follows is not None) for step in joint.free_steps()] == [
        ("turn", False),
        ("move", True),
        ("move", False),
    ]


def test_a_contradiction_found_while_implying_freedoms_is_reported(tmp_path):
    arm = _child(_rig(tmp_path, _links(), bore="motion: {type: universal, axis: [1, 0, 0]}"), "arm")
    assert any("turns twice about one axis" in problem for problem in arm.joint_problems)


def test_a_screw_with_no_thread_is_reported(tmp_path):
    arm = _child(_rig(tmp_path, _links(), bore="motion: screw"), "arm")
    assert any("threadStep" in problem for problem in arm.joint_problems)


#
# Where it is declared
#


def test_the_mating_outranks_the_interfaces(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    mating = """
        motion: fixed
    """
    assert _child(_rig(tmp_path, _links(), bore=bore, mating=mating), "arm").joint is None


def test_the_mating_states_its_axis_in_its_declarer_s_port_frame(tmp_path):
    # 'pin' declares the mating and is the connected object here, so its port
    # frame is the contact frame and +Z is +Z.
    mating = """
        motion:
          type: revolute
          limits: {lower: 0, upper: 30}
        physics:
          damping: 0.2
    """
    joint = _child(_rig(tmp_path, _links(), mating=mating), "arm").joint
    (free,) = joint.free_steps()
    assert (free.lower, free.upper) == (0.0, 30.0)
    assert free.source[0]["level"] == "mating"
    assert (joint.physics, joint.physics_source) == ({"damping": 0.2}, "mating")


def test_the_connection_outranks_the_mating(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    # A connection locks a joint for one test or one variant...
    assert _child(_rig(tmp_path / "a", _links("motion: fixed"), bore=bore), "arm").joint is None
    # ...and makes one out of a connection nothing else would let move.
    joint = _child(
        _rig(
            tmp_path / "b", _links("motion: {type: prismatic}\n      physics: {damping: 3}\n      toParams: {moveZ: 2}")
        ),
        "arm",
    ).joint
    (free,) = joint.free_steps()
    # In the contact frame, where 'toParams' are read: +Z, value 2.
    assert (free.kind, free.axis, free.value) == ("move", [0.0, 0.0, 1.0], 2.0)
    assert free.source[0]["level"] == "connection"
    assert (joint.physics, joint.physics_source) == ({"damping": 3}, "connection")


def test_motion_is_inherited_by_an_interface_that_is_a_drop_in(tmp_path):
    interfaces = """
        bearing:
          inherits: bore
        pattern:
          inherits:
            bore:
              left: [[-10, 0, 0], [0, 0, 1], 0]
              right: [[10, 0, 0], [0, 0, 1], 0]
    """
    ctx = _package(tmp_path, _links(), bore="motion: continuous", interfaces=interfaces)
    # The parent under another name moves as the parent does...
    assert ctx.get_interface(":bearing").get_motion() == "continuous"
    # ...and two bores side by side are not a bore that turns.
    assert ctx.get_interface(":pattern").get_motion() is None


#
# Physics
#


def test_one_side_s_physics_is_the_joint_s(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}"
    pin = "physics: {damping: 0.3}"
    joint = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm").joint
    assert joint.physics == {"damping": 0.3} and joint.physics_source.endswith(":pin")


def test_both_sides_disagreeing_on_a_merged_freedom_is_reported(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}\nphysics: {damping: 0.1, maxEffort: 1}"
    pin = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}\nphysics: {damping: 0.2, maxEffort: 1}"
    arm = _child(_rig(tmp_path, _links(), bore=bore, pin=pin), "arm")
    assert arm.joint.physics == {"damping": 0.1, "maxEffort": 1}
    (problem,) = arm.joint_problems
    assert "'damping'" in problem and "the degree of freedom they share" in problem
    assert ("arm", problem) in asyncio.run(_reload(tmp_path).get_connect_problems())


def test_the_mating_settles_what_the_two_sides_disagree_on(tmp_path):
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}\nphysics: {damping: 0.1}"
    pin = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}\nphysics: {damping: 0.2}"
    mating = "physics: {damping: 0.15}"
    arm = _child(_rig(tmp_path, _links(), bore=bore, pin=pin, mating=mating), "arm")
    assert arm.joint.physics == {"damping": 0.15} and arm.joint_problems == []


#
# What is wrong with a declaration
#


def test_a_type_and_a_dof_that_disagree_are_reported_and_dof_wins(tmp_path):
    bore = "parameters: {moveZ: [0, 5]}\nmotion: {type: revolute, dof: [moveZ]}"
    arm = _child(_rig(tmp_path, _links(), bore=bore), "arm")
    assert [step.kind for step in arm.joint.free_steps()] == ["move"]
    assert any("do not describe the same degrees of freedom" in problem for problem in arm.joint_problems)


def test_a_type_and_a_dof_that_agree_take_the_range_from_the_type(tmp_path):
    bore = "parameters: {turnZ: [-360, 360]}\nmotion: {type: continuous, dof: [turnZ]}"
    arm = _child(_rig(tmp_path, _links(), bore=bore), "arm")
    (free,) = arm.joint.free_steps()
    assert (free.lower, free.upper) == (None, None) and arm.joint_problems == []


def test_a_dof_naming_no_parameter_is_reported(tmp_path):
    arm = _child(_rig(tmp_path, _links(), bore="motion: {dof: [wobble]}"), "arm")
    assert arm.joint is None
    assert any(
        "'wobble'" in problem and "not a freedom-of-movement parameter" in problem for problem in arm.joint_problems
    )


def test_a_predefined_name_need_not_be_declared(tmp_path):
    arm = _child(_rig(tmp_path, _links(), bore="motion: {dof: [turnZ]}"), "arm")
    (free,) = arm.joint.free_steps()
    assert (free.lower, free.upper) == (None, None) and arm.joint_problems == []


@pytest.mark.parametrize("declared", ["parameters: [turnZ]", "parameters:\n  turnZ:", "parameters: {turnZ: {}}"])
def test_a_parameter_declared_by_name_alone_is_an_unlimited_freedom(tmp_path, declared):
    # Normalization writes '0..0' for it, which as a joint would be locked.
    arm = _child(_rig(tmp_path, _links(), bore=declared + "\nmotion: {dof: [turnZ]}"), "arm")
    (free,) = arm.joint.free_steps()
    assert (free.lower, free.upper) == (None, None) and not free.source[0]["synthesized"]


def test_a_self_contradicting_motion_is_reported_by_the_connect_check(tmp_path):
    _rig(tmp_path, _links(), bore="motion: {type: fixed, dof: [turnZ]}")
    problems = asyncio.run(_reload(tmp_path).get_connect_problems())
    assert any("keeps no degree of freedom" in problem for _, problem in problems)


def _reload(tmp_path):
    return pc.Context(str(tmp_path))._get_assembly(":rig")


#
# Identity
#


def test_a_joint_is_named_after_its_links_unless_the_connection_names_it(tmp_path):
    bore = "motion: revolute"
    links = """
    links:
      - part: base
      - part: arm
        name: upper_arm
        connect: {name: base, with: pin, to: bore, joint: shoulder_pan}
    """
    assembly = _rig(tmp_path, links, bore=bore)
    assert [joint.name for _, joint in assembly.joints()] == ["shoulder_pan"]


def test_duplicate_joint_names_are_suffixed_in_link_order_and_reported(tmp_path):
    links = """
    links:
      - part: base
      - part: lid
        name: leg
        connect: {name: base, with: pin, to: bore}
      - part: lid
        name: leg
        connect: {name: base, with: pin, to: bore}
      - part: lid
        name: leg
        connect: {name: base, with: pin, to: bore}
    """
    assembly = _rig(tmp_path, links, bore="motion: revolute")
    assert [joint.name for _, joint in assembly.joints()] == ["leg-base", "leg-base-2", "leg-base-3"]
    problems = asyncio.run(_reload(tmp_path).get_connect_problems())
    assert len([p for _, p in problems if "is taken by the link 'leg'" in p]) == 2


def test_joints_inside_a_container_are_named_by_their_path(tmp_path):
    links = """
    links:
      - name: gearbox
        links:
          - part: base
          - part: arm
            connect: {name: base, with: pin, to: bore}
    """
    assembly = _rig(tmp_path, links, bore="motion: revolute")
    ((prefix, joint),) = assembly.joints()
    assert joint.info(prefix)["parent"] == "gearbox/base" and joint.info(prefix)["child"] == "gearbox/arm"


def test_a_scene_attaches_nothing(tmp_path):
    _rig(tmp_path, _links("toParams: {turnZ: 10}"), bore="motion: revolute")
    scene = pc.Context(str(tmp_path)).get_scene(":table")
    asyncio.run(scene.do_instantiate())
    arm = _child(scene, "arm")
    assert arm.joint is None
    # ...but places exactly as the assembly does, the implied 'turnZ' included.
    assert _same(arm.location, _child(_reload_instantiated(tmp_path), "arm").location)


def _reload_instantiated(tmp_path):
    assembly = _reload(tmp_path)
    asyncio.run(assembly.do_instantiate())
    return assembly


#
# Closed loops
#


def test_a_connection_that_would_close_a_loop_is_refused(tmp_path):
    links = """
    links:
      - part: base
      - part: lid
        name: a
        connect: {name: b, with: pin, to: bore}
      - part: lid
        name: b
        connect: {name: a, with: pin, to: bore}
    """
    assembly = _rig(tmp_path, links)
    a = _child(assembly, "a")
    assert a.composition is None
    assert any("closes a loop (a -> b -> a)" in problem for problem in a.joint_problems)


def test_a_link_placed_twice_is_refused_the_second_time(tmp_path):
    links = """
    links:
      - part: base
      - part: arm
        location: [[0, 0, 0], [0, 0, 1], 0]
        connect: {name: base, with: pin, to: bore}
    """
    arm = _child(_rig(tmp_path, links), "arm")
    assert arm.composition is None
    assert any("placed by 'location' and again by 'connect'" in problem for problem in arm.joint_problems)


def test_a_connection_to_itself_is_refused(tmp_path):
    links = """
    links:
      - part: base
      - part: arm
        connect: {name: arm}
    """
    arm = _child(_rig(tmp_path, links), "arm")
    assert any("connected to itself" in problem for problem in arm.joint_problems)


#
# The placement, kept
#


def test_a_root_location_is_composed_on_top_of_the_steps(tmp_path):
    links = """
    location: [[5, 6, 7], [1, 0, 0], 30]
    links:
      - part: base
      - part: arm
        connect: {name: base, with: pin, to: bore, toParams: {turnZ: 12}}
    """
    arm = _child(_rig(tmp_path, links, bore="motion: revolute"), "arm")
    assert _same(arm.composition.location(), arm.location)
    # The joint relates the arm to the base, which moved with it.
    assert arm.joint.composition.outer is not None


def test_the_joint_rides_on_the_node_of_the_child_it_moves(tmp_path):
    """What an exporter that walks the tree finds: the joint, beside the properties."""
    bore = "parameters: {turnZ: [-90, 90]}\nmotion: {dof: [turnZ]}\nphysics: {damping: 0.4}"
    assembly = _rig(tmp_path, _links("toParams: {turnZ: 5}"), bore=bore)

    async def fake_wrapped(ctx):
        return {"name": "pkg:x", "label": "x", "brep": b"BREP"}

    for child in assembly.children:
        child.item.get_wrapped = fake_wrapped
    tree = asyncio.run(assembly._get_shape_real(None))

    base, arm = tree[shape_envelope.KEY_ASSEMBLY]
    assert shape_envelope.KEY_JOINT not in base
    joint = arm[shape_envelope.KEY_JOINT]
    assert (joint["name"], joint["parent"], joint["child"]) == ("arm-base", "base", "arm")
    free = [step for step in joint["steps"] if step["type"] == "free"]
    assert free == [
        {
            "type": "free",
            "kind": "turn",
            "axis": [0.0, 0.0, 1.0],
            "lower": -90,
            "upper": 90,
            "value": 5.0,
            "source": free[0]["source"],
            "coupling": None,
        }
    ]
    assert joint["physics"] == {"damping": 0.4}
    # Plain data, so it survives the codec every hop uses unchanged.
    assert shape_envelope.loads(shape_envelope.dumps(tree))[shape_envelope.KEY_ASSEMBLY][1]["joint"] == joint
    # And the node's placement is its target's times the steps, as data.
    product = Location(base[shape_envelope.KEY_LOCATION]) if base.get(shape_envelope.KEY_LOCATION) else Location()
    for step in joint["steps"]:
        if step["type"] == "fixed":
            product = product * Location(step["location"])
        elif step["value"]:
            product = product * pc.interface.movement_offset(step["kind"], step["axis"], step["value"])
    placed = Location(arm[shape_envelope.KEY_LOCATION])
    assert product.translation == pytest.approx(placed.translation)


def test_a_decode_false_exporter_is_handed_the_joints(tmp_path, wrapper_export):
    """The request travels as the core serializes it and is read raw, as the wrapper reads it."""
    bore = "motion: revolute"
    assembly = _rig(tmp_path, _links(), bore=bore)

    async def fake_wrapped(ctx):
        return {"name": "pkg:x", "label": "x", "brep": b"BREP"}

    for child in assembly.children:
        child.item.get_wrapped = fake_wrapped
    tree = asyncio.run(assembly._get_shape_real(None))
    request = shape_envelope.loads(shape_envelope.serialize({"wrapped": tree, "__decode__": False}))

    script = tmp_path / "joints.py"
    script.write_text(textwrap.dedent("""
            import json

            def process(path, request):
                found = []
                def walk(node):
                    if request_key in node:
                        found.append(node[request_key]["name"])
                    for child in node.get("assembly") or []:
                        walk(child)
                walk(request["wrapped"])
                with open(path, "w") as f:
                    json.dump(found, f)
                return {"success": True}
            """).replace("request_key", repr(wrapper_export.JOINT_KEY)))
    out = tmp_path / "joints.json"
    assert wrapper_export.process(str(script), str(out), request)["success"]
    assert out.read_text() == '["arm-base"]'


@pytest.fixture
def wrapper_export():
    """'wrappers/wrapper_export.py', imported without the sandbox around it.

    The way 'test_output.py' imports it: only the serialization helpers of
    'wrapper_common' are stubbed out, since that one reaches for a CAD stack.
    """
    import importlib.util
    import sys

    wrappers = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "wrappers")

    class _Stub:
        @staticmethod
        def exception_to_str(exc):
            return None if exc is None else str(exc)

        @staticmethod
        def handle_exception(exc, script=None):
            pass

    saved = sys.modules.get("wrapper_common")
    sys.modules["wrapper_common"] = _Stub
    saved_path = list(sys.path)
    sys.path.insert(0, wrappers)
    try:
        spec = importlib.util.spec_from_file_location(
            "partcad_test_joint_wrapper_export", os.path.join(wrappers, "wrapper_export.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path
        if saved is None:
            del sys.modules["wrapper_common"]
        else:
            sys.modules["wrapper_common"] = saved


def test_the_joint_module_spells_the_half_turn_as_the_placement_did():
    # 'facing()' is the exact map of the rotation the placement composes.
    for direction in [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.3, -0.4, 0.5)]:
        assert pc_joint.FACING.rotate_vector(direction) == pytest.approx(pc_joint.facing(direction))
