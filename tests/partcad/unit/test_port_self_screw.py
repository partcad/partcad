#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A port that cuts its own way into whatever it is joined to ('selfScrew').

An interface says 'selfScrew' of every joint made through it, and a mating of
every joint between its two interfaces. A connection that names ports alone
('withPort:', 'connectPorts:') looks up neither, so neither reaches it - and a
nail placed by its point was reported as overlapping the post it was driven
into, which is the overlap a nail exists to make. A port says it of itself, so
it reaches every joint made through that port however the joint was named.

Every test builds a small package of its own and instantiates an assembly of
it, which reads the declarations and nothing else: no geometry is built, so
none of this needs a sandbox.
"""

import asyncio
import os
import shutil
import textwrap
from unittest import mock

import partcad as pc
from partcad.interface import InterfacePort
from partcad.port import port_info
from partcad.test import interference

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")

PACKAGE = """
interfaces:
  entry:
    ports:
      entry:
  # A nail's point: it makes its own hole, wherever it goes.
  point:
    ports:
      tip:
        location: [[0, 0, 0], [0, 0, 1], 0]
        selfScrew: true
    mates: entry
  # What inherits it keeps it, the port being the same port.
  point-outdoor:
    inherits:
      point:
parts:
  post:
    type: stl
    path: cube.stl
    implements:
      entry:
        A: [[0, 0, 10], [1, 0, 0], 180]
        B: [[5, 0, 10], [1, 0, 0], 180]
  nail:
    type: stl
    path: cube.stl
    implements:
      point:
  outdoor-nail:
    type: stl
    path: cube.stl
    implements:
      point-outdoor:
  # A part's own port says it the same way.
  pin:
    type: stl
    path: cube.stl
    ports:
      tip:
        location: [[0, 0, 0], [0, 0, 1], 0]
        selfScrew: true
  peg:
    type: stl
    path: cube.stl
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
assemblies:
  rig:
    type: assy
    path: rig.assy
  # A nail ready to drive, by the point it externalizes.
  held:
    type: assy
    path: held.assy
    map:
      tip: [nail, tip]
"""

HELD = """
links:
  - part: nail
"""


def _ctx(root, links):
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(CUBE, root / "cube.stl")
    (root / "partcad.yaml").write_text(PACKAGE)
    (root / "held.assy").write_text(textwrap.dedent(HELD))
    (root / "rig.assy").write_text(textwrap.dedent(links))
    return pc.Context(str(root))


def _rig(root, links):
    ctx = _ctx(root, links)
    assembly = ctx._get_assembly(":rig")
    asyncio.run(assembly.do_instantiate())
    return ctx, assembly


def _child(assembly, name):
    return next(child for child in assembly.children if child.name == name)


def _ports(ctx, name):
    return asyncio.run(ctx._get_part_async(":" + name)).with_ports.get_ports()


def test_a_port_says_it_of_itself(tmp_path):
    ctx = _ctx(tmp_path, "links: []")
    assert _ports(ctx, "pin")["tip"].self_screw is True
    assert _ports(ctx, "peg")["tip"].self_screw is False


def test_every_copy_of_an_interfaces_port_keeps_it(tmp_path):
    """The 'tip' a nail has is a copy of the interface's, made as the nail
    implements it - and so is the one of a nail implementing an interface that
    inherits it."""
    ctx = _ctx(tmp_path, "links: []")
    assert _ports(ctx, "nail")["tip"].self_screw is True
    assert _ports(ctx, "outdoor-nail")["tip"].self_screw is True


def test_a_connection_by_ports_alone_goes_by_it(tmp_path):
    """Named by its ports, the joint has no interface and no mating to ask,
    and the port is what says how it is made."""
    _, assembly = _rig(
        tmp_path,
        """
        links:
          - part: post
          - part: pin
            connectPorts: {with: tip, name: post, to: A-entry}
          - part: peg
            connectPorts: {with: tip, name: post, to: B-entry}
        """,
    )
    pin = _child(assembly, "pin")
    assert pin.how.self_screw is True
    # Which is a statement of how it goes in, and so a step that can be followed.
    assert pin.how.motion_declared()
    assert _child(assembly, "peg").how.self_screw is False


def test_so_does_one_that_names_its_interfaces(tmp_path):
    _, assembly = _rig(
        tmp_path,
        """
        links:
          - part: post
          - part: nail
            connect: {name: post, toInstance: A}
        """,
    )
    assert _child(assembly, "nail").how.self_screw is True


def test_the_overlap_it_makes_is_expected(tmp_path):
    ctx, assembly = _rig(
        tmp_path,
        """
        links:
          - part: post
          - part: pin
            connectPorts: {with: tip, name: post, to: A-entry}
          - part: peg
            connectPorts: {with: tip, name: post, to: B-entry}
        """,
    )
    plan = asyncio.run(interference._plan(ctx, assembly))
    assert ("pin", "post") in plan.expected
    assert ("peg", "post") not in plan.expected


def test_an_assembly_mapping_the_port_keeps_it(tmp_path):
    """'map:' makes a port of the assembly's own out of the nail's, and that
    one is driven in as the nail's is."""
    ctx, assembly = _rig(
        tmp_path,
        """
        links:
          - part: post
          - assembly: held
            connectPorts: {with: tip, name: post, to: A-entry}
        """,
    )
    assert _child(assembly, "held").how.self_screw is True


def test_a_connection_may_still_say_otherwise(tmp_path):
    """The joint's own 'how' is the most specific statement, as it is against
    an interface or a mating that says it."""
    _, assembly = _rig(
        tmp_path,
        """
        links:
          - part: post
          - part: pin
            connectPorts: {with: tip, name: post, to: A-entry, how: {selfScrew: false}}
        """,
    )
    assert _child(assembly, "pin").how.self_screw is False


def test_pc_info_says_it_where_it_is_said(tmp_path):
    ctx = _ctx(tmp_path, "links: []")
    assert port_info(_ports(ctx, "pin")["tip"])["selfScrew"] is True
    assert "selfScrew" not in port_info(_ports(ctx, "peg")["tip"])


def test_only_a_boolean_says_it():
    """A quoted "false" is a non-empty string, and would read as true."""
    with mock.patch("partcad.logging.error") as error:
        assert InterfacePort("tip", None, {"selfScrew": "false"}).self_screw is False
    assert "'selfScrew' must be true or false" in error.call_args[0][0]
