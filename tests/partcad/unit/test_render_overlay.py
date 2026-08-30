#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for what "pc render --with-ports/--with-interfaces" draws.

Where the ports are is worked out from the configuration alone - no geometry is
built and no sandbox is needed - so the answers are checked here directly,
against the example that has the most of them.
"""

import asyncio

import pytest

import partcad as pc
from partcad import output
from partcad.render_overlay import Overlay, collect_async, effective

EXAMPLES = "examples"
PACKAGE = "//pub/examples/partcad/feature_interface"


def _collect(name, kind="part", overlay=None):
    ctx = pc.init(EXAMPLES)
    project = ctx.get_project(PACKAGE)
    shape = project.get_part(name) if kind == "part" else project.get_assembly(name)
    return asyncio.run(collect_async(shape, ctx, overlay or Overlay(ports=True)))


def _implementation(section, config):
    return output.Implementation(section, "svg", config)


def test_overlay_of_reports_nothing_as_none():
    """The overwhelmingly common case is neither option, and it is one value."""
    assert Overlay.of() is None
    assert Overlay.of(ports=True).ports
    assert not Overlay.of(ports=True).interfaces
    assert Overlay.of(interfaces=True).interfaces
    everything = Overlay.of(all=True)
    assert everything.ports and everything.interfaces


def test_only_a_render_file_type_carries_an_overlay():
    """A STEP file is not a picture to draw ports on."""
    assert effective(Overlay(ports=True), _implementation(output.EXPORT, {})) is None
    assert effective(Overlay(ports=True), _implementation(output.RENDER, {})).ports


def test_a_file_type_can_ask_for_the_overlay_itself():
    """Which is how a package keeps a drawing of its ports checked in."""
    declared = _implementation(output.RENDER, {"with_ports": True})
    assert effective(None, declared).ports
    assert not effective(None, declared).interfaces
    assert effective(None, _implementation(output.RENDER, {})) is None


def test_the_option_adds_to_what_the_file_type_declared():
    """Neither overrides the other: both are somebody asking for a drawing."""
    both = effective(Overlay(interfaces=True), _implementation(output.RENDER, {"with_ports": True}))
    assert both.ports and both.interfaces


def test_a_part_reports_every_port_it_implements():
    records = _collect("example-bracket")
    ports = [record["port"] for record in records]
    # Four bolt holes on each face of the bracket, plus the two slotted feet.
    assert len(ports) == 10
    assert "inner-TL-3mm-thru-opening-m3" in ports
    assert "L-30mm-slotted-3mm-thru-opening-m4" in ports


def test_a_port_carries_the_interface_a_connect_would_name():
    records = {record["port"]: record for record in _collect("example-bracket")}
    hole = records["outer-BR-3mm-thru-opening-m3"]
    assert hole["interface"] == PACKAGE + ":nema-17-motor-bracket-3"
    # What is written on the drawing, where the package prefix is noise.
    assert hole["interface_label"] == "nema-17-motor-bracket-3"
    assert hole["instance"] == "outer"
    assert hole["owner"] == ""


def test_a_port_with_no_boundary_sketch_asked_for_carries_none():
    """The sketches are only built when the interfaces are to be drawn."""
    assert all("sketch" not in record for record in _collect("example-bracket"))


def test_an_assembly_reports_the_ports_of_everything_in_it():
    records = _collect("connect-mates", kind="assembly")
    ports = [record["port"] for record in records]
    assert "example-bracket:inner-TL-3mm-thru-opening-m3" in ports
    assert "example-motor:TL-4.5mm-hole-opening-m3" in ports
    assert "socket-head-m3-screw-6mm:6mm-long-screw-m3" in ports
    # The assembly the ASSY file's 'links:' becomes is no object of any package
    # and nobody names it in a 'connect:', so it is not in any of these names.
    assert not any("None" in port for port in ports)
    assert all(port.count(":") == 1 for port in ports)


def test_an_assembly_moves_a_childs_ports_where_it_put_the_child():
    """This is the whole point of the overlay on an assembly.

    Two ports that were connected end up at the same place, and one that was not
    does not - which is what makes a connection that went wrong visible as two
    frames that should have met and did not.
    """
    records = {record["port"]: record for record in _collect("connect-mates", kind="assembly")}
    connected = records["example-bracket:outer-TR-3mm-thru-opening-m3"]["location"][0]
    mated = records["example-motor:TR-4.5mm-hole-opening-m3"]["location"][0]
    elsewhere = records["example-bracket:inner-TR-3mm-thru-opening-m3"]["location"][0]

    assert connected == pytest.approx(mated, abs=1e-6)
    assert elsewhere != pytest.approx(mated, abs=1e-6)
    # Not the port's own coordinates in the part: the assembly moved it there.
    assert records["example-motor:TR-4.5mm-hole-opening-m3"]["owner"] == "example-motor"


def test_the_interfaces_overlay_brings_the_port_boundaries_along():
    """The circle of a hole, the profile of a rail: what makes an interface
    visible rather than merely named."""
    from partcad import shape_envelope

    records = _collect("example-bracket", overlay=Overlay(interfaces=True))
    assert records
    for record in records:
        placed = record["sketch"]
        assert placed, record["port"]
        # Still an envelope, placed as plain data: the geometry is only built
        # when the render sandbox decodes it.
        for component in placed:
            assert shape_envelope.is_shape_envelope(component)
            assert component[shape_envelope.KEY_LOCATION] == record["location"]
