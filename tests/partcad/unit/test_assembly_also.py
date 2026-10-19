#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The further joints a link makes once placed, and the connections that find them.

A link is placed once, by one connection. Anything that closes a loop - a rail
placed against one leg that meets the other one too, a top placed by one corner
that rests on all four - has a further joint, and 'alsoConnectPorts' states it:
checked once everything is placed, and recorded for the instruction book.

Every test builds a small package of its own and instantiates an assembly of
it, which reads the declarations and nothing else: no geometry is built, so
none of this needs a sandbox.
"""

import asyncio
import os
import shutil
import textwrap

import pytest

import partcad as pc
from partcad.test.connectivity import ConnectivityTest

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")

# A base with three ports on top, 20 mm apart along X, and a beam with two on
# its underside, 20 mm apart too: placed by one pair, the beam meets the base at
# the other. 'wrong-way' is where 'p2' is but facing up, out of the base, and
# 'p3' is 10 mm further. Each port's +Z points into its part. Mating two ports
# turns one to face the other, which swaps their X and Y: so the beam's second
# port is along its Y, which ends up along the base's X.
PACKAGE = """
parts:
  base:
    type: stl
    path: cube.stl
    ports:
      p1: [[0, 0, 10], [1, 0, 0], 180]
      p2: [[20, 0, 10], [1, 0, 0], 180]
      p3: [[30, 0, 10], [1, 0, 0], 180]
      wrong-way: [[20, 0, 10], [0, 0, 1], 0]
  beam:
    type: stl
    path: cube.stl
    ports:
      q1: [[0, 0, 0], [0, 0, 1], 0]
      q2: [[0, 20, 0], [0, 0, 1], 0]
  board:
    type: stl
    path: cube.stl
    implements:
      "slab;length=40":
  pin:
    type: stl
    path: cube.stl
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
interfaces:
  # Built from a parameter, as a board of any length is, and with a port that a
  # connection may move along it and into it.
  slab:
    parameters:
      length: 10.0
      fromEdge:
        type: move
        dir: [0, 1, 0]
        min: 0
        max: "%length%"
        default: 0
      drive:
        type: move
        dir: [0, 0, -1]
        min: 0
        max: 10
        default: 0
    ports:
      edge: [[0, 0, 10], [1, 0, 0], 180]
assemblies:
  rig:
    type: assy
    path: rig.assy
"""


def _rig(root, links):
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(CUBE, root / "cube.stl")
    (root / "partcad.yaml").write_text(PACKAGE)
    (root / "rig.assy").write_text(textwrap.dedent(links))
    assembly = pc.Context(str(root))._get_assembly(":rig")
    asyncio.run(assembly.do_instantiate())
    return assembly


def _child(assembly, name):
    return next(child for child in assembly.children if child.name == name)


def _beam(also, location=None):
    return """
    {location}
    links:
      - part: base
      - part: beam
        connectPorts: {{with: q1, name: base, to: p1}}
        alsoConnectPorts: {also}
    """.format(also=also, location="" if location is None else "location: %s" % location)


def test_a_further_joint_that_meets_is_recorded(tmp_path):
    beam = _child(_rig(tmp_path, _beam("{with: q2, name: base, to: p2, comment: Both ends rest on it.}")), "beam")
    assert beam.joint_problems == []
    (record,) = beam.also
    assert (record["name"], record["with"], record["to"], record["meets"]) == ("base", "q2", "p2", True)
    assert record["comment"] == "Both ends rest on it."
    # Where the two meet, in the assembly's frame: the base's port.
    assert record["point"] == pytest.approx([20, 0, 10])
    assert record["direction"] == pytest.approx([0, 0, -1])
    # And 'pc info' says so with the rest of what the file says about the link.
    assert beam.connect_info()["also"] == [
        {"name": "base", "with": "q2", "to": "p2", "comment": "Both ends rest on it."}
    ]


def test_a_further_joint_whose_ports_are_apart_is_a_problem(tmp_path):
    beam = _child(_rig(tmp_path, _beam("[{with: q2, name: base, to: p3}]")), "beam")
    (problem,) = beam.joint_problems
    assert "10.000 mm from the 'p3' port of 'base'" in problem
    assert beam.also[0]["meets"] is False


def test_a_further_joint_whose_ports_do_not_face_each_other_is_a_problem(tmp_path):
    beam = _child(_rig(tmp_path, _beam("{with: q2, name: base, to: wrong-way}")), "beam")
    (problem,) = beam.joint_problems
    assert "do not face each other" in problem


def test_a_further_joint_naming_a_port_that_is_not_there_is_a_problem(tmp_path):
    beam = _child(_rig(tmp_path, _beam("{with: q9, name: base, to: p2}")), "beam")
    (problem,) = beam.joint_problems
    assert "'q9' of 'beam', which has no such port (it has: q1, q2)" in problem
    assert beam.also == []


def test_a_further_joint_is_stated_on_the_later_link(tmp_path):
    links = """
    links:
      - part: base
      - part: beam
        name: first
        connectPorts: {with: q1, name: base, to: p1}
        alsoConnectPorts: {with: q2, name: second, to: q1}
      - part: beam
        name: second
        connectPorts: {with: q1, name: base, to: p2}
    """
    first = _child(_rig(tmp_path, links), "first")
    (problem,) = first.joint_problems
    assert "'second', which is placed after it" in problem


def test_a_further_joint_that_is_not_a_section_is_a_problem(tmp_path):
    beam = _child(_rig(tmp_path, _beam("[base]")), "beam")
    (problem,) = beam.joint_problems
    assert "takes sections of 'with', 'name' and 'to', not 'base'" in problem
    assert beam.also == []


def test_a_further_joint_says_which_of_its_fields_it_ignores(tmp_path):
    """'how' belongs to the connection that places a link: a further joint places nothing"""
    beam = _child(_rig(tmp_path, _beam("{with: q2, name: base, to: p2, how: {pushForceMax: 5}}")), "beam")
    (problem,) = beam.joint_problems
    assert "'alsoConnectPorts' has no field 'how'" in problem
    # The joint itself is still checked, and still meets.
    assert beam.also[0]["meets"] is True


def test_a_further_joint_without_its_ports_is_a_problem(tmp_path):
    beam = _child(_rig(tmp_path, _beam("{name: base}")), "beam")
    (problem,) = beam.joint_problems
    assert "needs a 'with', 'to'" in problem


def test_the_placement_of_the_root_moves_where_the_joints_are(tmp_path):
    """Worked out in the frame the file is written in, and read in the one it ends up in."""
    beam = _child(_rig(tmp_path, _beam("{with: q2, name: base, to: p2}", "[[0, 0, 0], [0, 0, 1], 90]")), "beam")
    assert beam.joint_problems == []
    assert beam.also[0]["point"] == pytest.approx([0, 20, 10], abs=1e-9)
    assert beam.connection["point"] == pytest.approx([0, 0, 10], abs=1e-9)


def test_an_interface_built_from_parameters_is_found_by_its_bare_name(tmp_path):
    """'slab' is what a connection can spell; the board implements 'slab;length=40'."""
    links = """
    links:
      - part: board
      - part: pin
        connect:
          name: board
          to: slab
          toPort: edge
          withPort: tip
          toParams: {fromEdge: 15, drive: 4}
    """
    pin = _child(_rig(tmp_path, links), "pin")
    assert pin.joint_problems == []
    assert pin.connection["to_interface"].endswith(":slab;length=40")
    # 15 mm along the port's X and 4 mm into the board: 'fromEdge' and 'drive'
    # are read in the contact frame, where the port's X is Y and its Z is -Z.
    assert pin.connection["contact"] == pytest.approx([15, 0, 6], abs=1e-9)


def test_a_bare_name_stands_for_one_parametrization_only(tmp_path):
    """A name spelled with parameters is that parametrization, or none"""
    board = _rig(tmp_path, "links:\n  - part: board\n").children[0].item
    (implemented,) = board.with_ports.get_interfaces()
    bare = implemented.split(";", 1)[0]
    assert implemented.endswith(":slab;length=40")
    assert board.with_ports.implemented_name(bare) == implemented
    assert board.with_ports.implemented_name(implemented) == implemented
    assert board.with_ports.implemented_name(bare + ";length=41") is None
    # The old spelling of an absolute name, with one slash, is read as the new one.
    assert bare.startswith("//")
    assert board.with_ports.implemented_name(bare[1:]) == implemented


def test_an_interface_the_target_does_not_implement_is_a_problem(tmp_path):
    links = """
    links:
      - part: board
      - part: pin
        connect: {name: board, to: nosuch, toPort: edge, withPort: tip}
    """
    pin = _child(_rig(tmp_path, links), "pin")
    assert any("'board' does not implement" in problem and "nosuch" in problem for problem in pin.joint_problems)


def _crowded(assembly):
    problems, _ = asyncio.run(ConnectivityTest()._crowded_ports(None, assembly.children))
    return problems


def test_two_things_on_one_port_at_two_places_do_not_crowd_it(tmp_path):
    """A screw 5 mm in from an edge and one 25 mm in are at two places of one port."""
    links = """
    links:
      - part: board
      {pins}
    """
    pin = """
      - part: pin
        name: pin-{n}
        connect: {{name: board, to: slab, toPort: edge, withPort: tip, toParams: {{fromEdge: {at}}}}}
    """
    apart = _rig(tmp_path / "apart", links.format(pins="".join(pin.format(n=n, at=at) for n, at in ((1, 5), (2, 25)))))
    assert _crowded(apart) == []
    same = _rig(tmp_path / "same", links.format(pins="".join(pin.format(n=n, at=5) for n in (1, 2))))
    (problem,) = _crowded(same)
    assert "'pin-1' and 'pin-2' are both connected to 'edge' of 'board'" in problem
