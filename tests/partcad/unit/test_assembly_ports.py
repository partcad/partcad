#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for 'map:' - the ports and interfaces an assembly externalizes.

Where a port ends up is 'geom.Location' algebra over the declaration and over
where the assembly put its children, so none of this builds geometry and none of
it needs a CAD kernel: the assemblies are walked, not made.
"""

import asyncio

import pytest

import partcad as pc
from partcad import shape_ports
from partcad.geom import Location

PACKAGE = "tests/partcad/unit/data/assembly_ports/partcad.yaml"


def _assembly(name):
    """One assembly of the test package, with its 'map:' resolved."""
    ctx = pc.init(PACKAGE)
    assembly = ctx._get_assembly(":" + name)
    asyncio.run(shape_ports.prepare_async(assembly, ctx))
    return ctx, assembly


def _ports(assembly):
    return {name: port for name, port in assembly.with_ports.get_ports().items()}


def _at(assembly, port_name):
    """Where one of an assembly's ports is, as a translation."""
    from partcad.interface import port_location

    return tuple(port_location(_ports(assembly)[port_name]).translation)


def test_a_mapped_port_is_a_port_of_the_assembly():
    """[node, port]: the child's port, under a name the assembly chose."""
    _, mount = _assembly("mount")
    assert "hold" in _ports(mount)
    # The lower plate is at the origin, and its 'handle' is 5mm above it.
    assert _at(mount, "hold") == pytest.approx((0.0, 0.0, 5.0))


def test_a_mapped_port_moves_with_the_node_that_carries_it():
    """The whole point: the port is where the assembly put the thing it is on."""
    _, mount = _assembly("mount")
    # The upper plate is 20mm up, and its TL hole is at (-10, 10) on it.
    assert _at(mount, "top-thru-m3") == pytest.approx((-10.0, 10.0, 20.0))
    assert _at(mount, "bottom-thru-m3") == pytest.approx((10.0, 10.0, 0.0))


def test_a_mapped_instance_keeps_the_interface_and_takes_a_new_name():
    """[node, interface, instance]: an interface is a contract, an instance is a place."""
    _, mount = _assembly("mount")
    interfaces = mount.with_ports.get_interfaces()
    assert "//:m3-thru" in interfaces
    # Two instances of one interface are two instances of it, not two of it.
    assert sorted(interfaces["//:m3-thru"].keys()) == ["bottom", "top"]
    # The ports are named the way an 'implements:' would have named them.
    assert interfaces["//:m3-thru"]["top"] == {"thru-m3": "top-thru-m3"}


def test_an_implements_may_place_an_interface_at_a_mapped_port():
    """Which is why the map is resolved before 'ports:' and 'implements:'."""
    _, mount = _assembly("mount")
    assert _at(mount, "held-grip") == _at(mount, "hold")
    assert list(mount.with_ports.get_interfaces()["//:grip"].keys()) == ["held"]


def test_an_assembly_that_externalizes_nothing_has_no_ports():
    """The same ASSY file, declared without a 'map:': what is inside it is its own business."""
    _, opaque = _assembly("mount_opaque")
    assert _ports(opaque) == {}
    assert opaque.with_ports.get_interfaces() == {}


def test_a_boundary_is_crossed_one_object_at_a_time():
    """An assembly maps what a sub-assembly externalized, not what is inside it."""
    _, column = _assembly("column")
    assert _at(column, "grab") == pytest.approx((0.0, 0.0, 5.0))
    assert _at(column, "anchor-thru-m3") == pytest.approx((-10.0, 10.0, 20.0))
    assert list(column.with_ports.get_interfaces()["//:m3-thru"].keys()) == ["anchor"]


def test_a_node_inside_a_container_is_reached_through_it():
    """A named 'links:' group is a path element; an anonymous one is not."""
    _, grouped = _assembly("grouped")
    assert _at(grouped, "inner") == pytest.approx((1.0, 2.0, 8.0))
    assert _at(grouped, "unnamed") == pytest.approx((0.0, 0.0, 12.0))


def test_the_nodes_a_map_may_name_are_the_assembly_file_s_own():
    """By node name, not by part name: an assembly places one part many times."""
    from partcad import assembly_ports

    ctx, mount = _assembly("mount")
    nodes = assembly_ports.node_index(mount)
    assert sorted(nodes.keys()) == ["lower", "upper"]
    # Both nodes are the same part, in two places.
    assert nodes["lower"][0] is nodes["upper"][0]
    assert tuple(nodes["upper"][1].translation) == pytest.approx((0.0, 0.0, 20.0))


def test_every_way_of_getting_it_wrong_is_reported_rather_than_raised(monkeypatch):
    """One unusable entry costs the user that port, not the assembly."""
    from partcad import logging as pc_logging

    errors = []
    monkeypatch.setattr(
        pc_logging, "error", lambda *args: errors.append(args[0] % args[1:] if len(args) > 1 else args[0])
    )

    _, broken = _assembly("broken")
    assert _ports(broken) == {}

    reported = "\n".join(errors)
    assert "there is no node 'nowhere'" in reported
    assert "has no port called 'nowhere'" in reported
    # Naming an interface where a port belongs says which of the two forms to use.
    assert "rather than a port of it" in reported
    assert "does not implement 'nowhere'" in reported
    assert "has no instance 'nowhere'" in reported
    assert "must name a node and a port" in reported


def test_a_port_with_no_location_is_at_the_origin_of_what_declares_it():
    """None is not a place. A connection made through such a port used to raise."""
    from partcad.interface import port_location

    ctx = pc.init(PACKAGE)
    plate = ctx.get_part(":plate")
    declared = plate.with_ports.get_ports()["origin"]
    assert declared.location is None
    assert port_location(declared).as_packed() == Location().as_packed()

    connected = ctx._get_assembly(":connect_origin")
    asyncio.run(connected.do_instantiate())
    placed = {child.name: child for child in connected.connected_children() if child.name}
    assert sorted(placed.keys()) == ["base", "pin"]
    assert tuple(placed["pin"].location.translation) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_something_can_be_connected_to_what_an_assembly_externalizes():
    """The point of all of it: an assembly connects the way a part does.

    The instance the mount externalized is an instance of 'm3-thru' like any
    other, so the screw mates with it - by mating alone, with neither end of the
    connection naming a port.
    """
    ctx = pc.init(PACKAGE)
    bolted = ctx._get_assembly(":bolted")
    asyncio.run(bolted.do_instantiate())

    placed = {child.name: child for child in bolted.connected_children() if child.name}
    assert tuple(placed["pin"].location.translation) == pytest.approx((-10.0, 10.0, 20.0))

    connection = placed["pin"].connection
    assert connection["to_interface"] == "//:m3-thru"
    assert connection["to_port"] == "top-thru-m3"


def test_a_mapped_port_counts_as_a_port_of_its_own():
    """An object that implements one interface *and* carries a loose port is not
    unambiguous, and a mapped port is a loose port."""
    ctx = pc.init(PACKAGE)
    plate = ctx.get_part(":plate")
    assert plate.with_ports.has_loose_ports()

    _, column = _assembly("column")
    # 'column' maps one port and one interface instance, and declares neither.
    assert "ports" not in column.with_ports.config
    assert column.with_ports.has_loose_ports()

    _, opaque = _assembly("mount_opaque")
    assert not opaque.with_ports.has_loose_ports()


def test_pc_info_reports_a_port_that_has_no_boundary_sketch():
    """A port may be a frame and nothing else, and saying so must not raise."""
    ctx = pc.init(PACKAGE)
    plate = ctx.get_part(":plate")
    reported = plate.with_ports.info()["ports"]
    assert reported["origin"] == {"location": Location().as_packed()}
    # Plain data, not a Location: this travels to a client over JSON-RPC.
    assert reported["TL-thru-m3"]["location"] == [[-10.0, 10.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    assert reported["TL-thru-m3"]["sketch"] == "//:m3"


def test_an_assembly_is_taken_at_its_word_unless_asked_otherwise():
    """The enumeration stops at the boundary: that is what externalizing means."""
    ctx, mount = _assembly("mount")

    own = {record.name for record in asyncio.run(shape_ports.ports_async(mount, ctx))}
    assert own == {"hold", "top-thru-m3", "bottom-thru-m3", "held-grip"}

    deep = {record.name for record in asyncio.run(shape_ports.ports_async(mount, ctx, deep=True))}
    assert own < deep
    # Named by the node that holds them, and moved by where the assembly put it.
    assert "upper:TL-thru-m3" in deep
    inside = [record for record in asyncio.run(shape_ports.ports_async(mount, ctx, deep=True))]
    upper = [record for record in inside if record.name == "upper:TL-thru-m3"][0]
    assert tuple(upper.location.translation) == pytest.approx((-10.0, 10.0, 20.0))


def test_searching_by_interface_finds_what_declares_it_and_what_maps_it():
    """Read from the declarations: nothing is instantiated to answer this."""
    from partcad.actions.shape import search_assemblies, search_parts

    ctx = pc.init(PACKAGE)
    package = "//"

    parts = [part.name for part in search_parts(ctx, package, False, "", "m3-thru")]
    assert parts == ["plate"]

    # The abstract interface a family derives from is exactly what a search is
    # written against, so the closure is walked upwards.
    assert [part.name for part in search_parts(ctx, package, False, "", "m3")] == ["plate", "screw"]

    # An assembly is found by what its 'map:' externalizes, without resolving it.
    assemblies = [assembly.name for assembly in search_assemblies(ctx, package, False, "", "m3-thru")]
    assert sorted(assemblies) == ["broken", "column", "mount"]

    # And the keyword still applies on top of it.
    assert [part.name for part in search_parts(ctx, package, False, "screw", "m3")] == ["screw"]
    assert search_parts(ctx, package, False, "", "//:nothing-like-this") == []


def test_the_search_index_is_built_once_and_not_before_it_is_asked_for():
    """'pc list' must not pay for an index it never reads."""
    from partcad.actions.shape import search_parts

    ctx = pc.init(PACKAGE)
    project = ctx.get_project("//")
    # A context is shared between the tests in this process, so start from what
    # a package that nobody has searched yet looks like.
    project.interface_indexes.clear()

    # What 'pc list parts' reads, and all it reads.
    assert [part.name for part in project.parts.values()] == ["plate", "screw"]
    assert project.interface_indexes == {}

    search_parts(ctx, "//", False, "", "m3-thru")
    assert "part" in project.interface_indexes
    first = project.interface_indexes["part"]
    search_parts(ctx, "//", False, "", "m3")
    assert project.interface_indexes["part"] is first
