#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The connection resolver, called on its own.

'AssemblyFactoryAssy.resolve_connection' is the step of placing a link that
turns its 'connect*' section, the child and the target into a placement. It
takes the target and the target's location as arguments, so that a route end
(issue #975) can hand it an item further down the tree. Called directly, it
has to give exactly what placing the link gave, and its placement has to follow
the target location it is handed.

Every test instantiates a small package of its own, which reads declarations
and builds no geometry.
"""

import asyncio
import os
import shutil
import textwrap

import pytest

import partcad as pc
from partcad import assembly_factory_assy
from partcad.assembly_factory_assy import AssemblyFactoryAssy
from partcad.geom import Location

CUBE = os.path.join("examples", "produce_part_stl", "cube.stl")

PACKAGE = """
parts:
  base:
    type: stl
    path: cube.stl
    ports:
      p1: [[0, 0, 10], [1, 0, 0], 180]
  beam:
    type: stl
    path: cube.stl
    ports:
      q1: [[5, 3, 0], [0, 0, 1], 30]
  board:
    type: stl
    path: cube.stl
    implements:
      "slab;length=40":
  key:
    type: stl
    path: cube.stl
    implements:
      tab:
  pin:
    type: stl
    path: cube.stl
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
  blank:
    type: stl
    path: cube.stl
interfaces:
  slab:
    parameters:
      length: 10.0
      fromEdge:
        type: move
        dir: [0, 1, 0]
        min: 0
        max: "%length%"
        default: 0
    ports:
      edge: [[0, 0, 10], [1, 0, 0], 180]
  tab:
    ports:
      face: [[2, 0, 0], [0, 0, 1], 0]
assemblies:
  rig:
    type: assy
    path: rig.assy
"""

# Where a target is moved to, to see the placement follow it.
SHIFTED = Location((7, -4, 12), (0, 1, 1), 40)


def _same(a, b):
    """Exact equality of two locations: the same numbers, not nearly them."""
    return a._t == b._t and a._q == b._q


def _resolve(root, monkeypatch, links):
    """Instantiate the rig, and on each 'resolve_connection' the link makes,
    call it again directly: once with the same arguments, once with the target
    moved to SHIFTED. Returns the assembly and what each call gave, per link."""
    calls = {}
    original = AssemblyFactoryAssy.resolve_connection

    async def recording(self, item, name, spec, target_part, target_location):
        placed = await original(self, item, name, spec, target_part, target_location)
        direct = await original(self, item, name, spec, target_part, target_location)
        shifted = await original(self, item, name, spec, target_part, SHIFTED)
        calls[name] = (placed, direct, shifted, target_location)
        return placed

    monkeypatch.setattr(AssemblyFactoryAssy, "resolve_connection", recording)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(CUBE, root / "cube.stl")
    (root / "partcad.yaml").write_text(PACKAGE)
    (root / "rig.assy").write_text(textwrap.dedent(links))
    assembly = pc.Context(str(root))._get_assembly(":rig")
    asyncio.run(assembly.do_instantiate())
    return assembly, calls


def _child(assembly, name):
    return next(child for child in assembly.children if child.name == name)


def _check(assembly, calls, name):
    """The direct call gives what placing the link gave, and follows its target."""
    child = _child(assembly, name)
    placed, direct, shifted, target_location = calls[name]
    assert _same(child.location, placed.location)
    assert _same(direct.location, child.location)
    assert direct.joint_problems == child.joint_problems
    assert direct.connection == child.connection
    assert direct.source_port is placed.source_port
    assert direct.target_port is placed.target_port
    # Relative to its target, the placement is the same wherever the target is.
    relative = target_location.inverse() * child.location
    expected = SHIFTED * relative
    assert shifted.location.translation == pytest.approx(expected.translation, abs=1e-9)
    assert shifted.location._q == pytest.approx(expected._q, abs=1e-12)
    return child, placed


def test_a_link_placed_by_ports(tmp_path, monkeypatch):
    links = """
    links:
      - part: base
        location: [[1, 2, 3], [0, 0, 1], 15]
      - part: beam
        connectPorts: {with: q1, name: base, to: p1}
    """
    assembly, calls = _resolve(tmp_path, monkeypatch, links)
    beam, placed = _check(assembly, calls, "beam")
    assert beam.joint_problems == []
    assert placed.source_port.name.endswith("q1")
    assert placed.target_port.name.endswith("p1")


def test_a_link_placed_by_interfaces(tmp_path, monkeypatch):
    links = """
    links:
      - part: board
      - part: key
        connect: {with: tab, name: board, to: slab}
    """
    assembly, calls = _resolve(tmp_path, monkeypatch, links)
    key, placed = _check(assembly, calls, "key")
    assert key.joint_problems == []
    assert placed.source_iface_obj is not None and placed.target_iface_obj is not None
    assert key.connection["to_interface"].endswith(":slab;length=40")


def test_a_link_placed_with_target_parameters(tmp_path, monkeypatch):
    links = """
    links:
      - part: board
      - part: pin
        connect:
          name: board
          to: slab
          toPort: edge
          withPort: tip
          toParams: {fromEdge: 15}
    """
    assembly, calls = _resolve(tmp_path, monkeypatch, links)
    pin, _ = _check(assembly, calls, "pin")
    assert pin.joint_problems == []
    # 15 mm along the port's X, which the contact frame holds as Y.
    assert pin.connection["contact"] == pytest.approx([15, 0, 10], abs=1e-9)


def test_a_port_less_child_still_warns_of_auto_detection(tmp_path, monkeypatch):
    warnings = []
    warning = assembly_factory_assy.pc_logging.warning

    def recording(message, *args, **kwargs):
        warnings.append(message % args if args else message)
        warning(message, *args, **kwargs)

    monkeypatch.setattr(assembly_factory_assy.pc_logging, "warning", recording)
    links = """
    links:
      - part: pin
      - part: blank
        connectPorts: {name: pin, to: tip}
    """
    assembly, calls = _resolve(tmp_path, monkeypatch, links)
    _, placed = _check(assembly, calls, "blank")
    assert placed.source_port is None
    # Placing the link, and each of the two direct calls.
    assert warnings.count("Peer port auto-detection has failed: blank") == 3
