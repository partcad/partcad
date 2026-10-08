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


def test_a_map_may_be_written_in_terms_of_the_assembly_s_parameters():
    """An assembly parametrized by what it holds names its nodes after them."""
    ctx = pc.init(PACKAGE)
    for which, height in (("lower", 5.0), ("upper", 25.0)):
        assembly = ctx._get_assembly(":parametric", {"which": which})
        asyncio.run(shape_ports.prepare_async(assembly, ctx))
        assert _at(assembly, "chosen") == pytest.approx((0.0, 0.0, height))


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
    assert "must be a list" in reported


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

    # A part is found by what it implements, and by an interface its 'map:'
    # names (the long form states it, even in an entry that is otherwise wrong).
    parts = [part.name for part in search_parts(ctx, package, False, "", "m3-thru")]
    assert sorted(parts) == ["broken-plate", "named-plate", "plate"]

    # The abstract interface a family derives from is exactly what a search is
    # written against, so the closure is walked upwards.
    parts = [part.name for part in search_parts(ctx, package, False, "", "m3")]
    assert sorted(parts) == ["broken-plate", "named-plate", "plate", "screw"]

    # An assembly is found by what its 'map:' externalizes, without resolving it.
    assemblies = [assembly.name for assembly in search_assemblies(ctx, package, False, "", "m3-thru")]
    assert sorted(assemblies) == ["broken", "column", "mount", "mount-renamed"]

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
    assert [part.name for part in project.parts.values()] == [
        "plate",
        "screw",
        "named-plate",
        "raised-plate",
        "scaled-plate",
        "relabelled-plate",
        "broken-plate",
    ]
    assert project.interface_indexes == {}

    search_parts(ctx, "//", False, "", "m3-thru")
    assert "part" in project.interface_indexes
    first = project.interface_indexes["part"]
    search_parts(ctx, "//", False, "", "m3")
    assert project.interface_indexes["part"] is first


def test_a_port_inside_an_assembly_is_named_by_every_level_above_it():
    """The node path, container levels included, then the port.

    It used to skip the containers an ASSY file embeds, on the grounds that
    nothing could name one - and that made two ports in two such containers the
    same address. Every link has a name now ('Assembly.link_name'), so the path
    is the path, and it is the same path the viewer shows as rows and the same
    string 'pc render --port' takes.
    """
    ctx = pc.init(PACKAGE)
    grouped = ctx._get_assembly(":grouped")
    records = asyncio.run(shape_ports.ports_async(grouped, ctx, deep=True))
    names = {record.name for record in records}

    assert "frame:plate:handle" in names
    # The second 'links:' names itself nothing, so it is 'link#2' - and the two
    # plates' ports are told apart rather than sharing one address.
    assert "link#2:loose:handle" in names


# --- a map of what the object has of its own --------------------------------


def _part(name):
    """One part of the test package, with its 'map:' resolved."""
    ctx = pc.init(PACKAGE)
    part = ctx.get_part(":" + name)
    asyncio.run(shape_ports.prepare_async(part, ctx))
    return ctx, part


def _frame(shape, port_name):
    from partcad.interface import port_location

    return port_location(_ports(shape)[port_name])


def test_an_enrich_maps_a_port_of_what_it_points_at():
    """[port]: no node, so the port is the object's own - its source's, for an enrich."""
    _, plate = _part("named-plate")
    assert _at(plate, "lift") == pytest.approx((0.0, 0.0, 5.0))


def test_an_enrich_with_a_map_keeps_the_ports_of_what_it_points_at():
    """The names it maps are added to the ones it has, not put in their place."""
    _, plate = _part("named-plate")
    ports = _ports(plate)
    for name in ("handle", "origin", "TL-thru-m3", "TR-thru-m3", "lift", "raised"):
        assert name in ports
    assert sorted(plate.with_ports.get_interfaces()["//:m3-thru"].keys()) == ["TL", "TR", "corner"]


def test_a_mapped_port_may_be_moved_and_turned_in_its_own_frame():
    """The moves, then the turns, in the frame of what is named."""
    _, plate = _part("named-plate")
    raised = _frame(plate, "raised")
    assert tuple(raised.translation) == pytest.approx((0.0, 0.0, 7.0))
    # Turned a quarter turn about its own Z: its X is where its Y was.
    assert tuple(raised.rotate_vector((1.0, 0.0, 0.0))) == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


def test_an_interface_instance_may_be_mapped_and_moved():
    """A new instance of the same interface, a millimetre beside the old one."""
    _, plate = _part("named-plate")
    assert _at(plate, "corner-thru-m3") == pytest.approx((-11.0, 10.0, 0.0))


def test_mapping_an_instance_does_not_add_it_to_the_source():
    """The interfaces an enrich adopts are its own copies: 'corner' is the
    enrich's instance, not the plate's or that of every other reference to it."""
    ctx, named = _part("named-plate")
    assert "corner" in named.with_ports.get_interfaces()["//:m3-thru"]
    plate = ctx.get_part(":plate")
    asyncio.run(shape_ports.prepare_async(plate, ctx))
    assert sorted(plate.with_ports.get_interfaces()["//:m3-thru"].keys()) == ["TL", "TR"]
    assert "corner-thru-m3" not in plate.with_ports.get_ports()


def test_a_reference_s_offset_moves_what_it_maps_of_its_source():
    _, plate = _part("raised-plate")
    assert _at(plate, "lift") == pytest.approx((0.0, 0.0, 15.0))


def test_a_reference_that_scales_cannot_map_its_source_s_ports(monkeypatch):
    from partcad import logging as pc_logging

    errors = []
    monkeypatch.setattr(
        pc_logging, "error", lambda *args: errors.append(args[0] % args[1:] if len(args) > 1 else args[0])
    )
    _, plate = _part("scaled-plate")
    assert "lift" not in _ports(plate)
    assert any("which it scales" in error for error in errors)


def test_an_object_that_is_no_reference_maps_what_it_declares():
    _, plate = _part("relabelled-plate")
    assert _at(plate, "a") == pytest.approx((1.0, 2.0, 3.0))
    assert _at(plate, "b") == pytest.approx((2.0, 2.0, 3.0))


def test_an_enriched_assembly_maps_what_its_source_externalizes():
    _, mount = _assembly("mount-renamed")
    assert _at(mount, "handle") == pytest.approx((0.0, 0.0, 5.0))
    # The source's 'top' is its upper plate's TL hole, 20mm up.
    assert _at(mount, "shifted-thru-m3") == pytest.approx((-10.0, 10.0, 25.0))


def test_a_node_s_port_may_be_externalized_beside_where_it_is():
    _, mount = _assembly("mount-offset")
    assert _at(mount, "beside") == pytest.approx((3.0, 0.0, 5.0))


def test_every_way_of_getting_the_long_form_wrong_is_reported(monkeypatch):
    from partcad import logging as pc_logging

    errors = []
    monkeypatch.setattr(
        pc_logging, "error", lambda *args: errors.append(args[0] % args[1:] if len(args) > 1 else args[0])
    )

    _, plate = _part("broken-plate")
    ports = _ports(plate)
    # What it points at is still there; what it maps is not.
    assert "handle" in ports
    for name in ("neither", "both", "unknown_key", "instance_alone", "not_a_number", "node_on_a_part"):
        assert name not in ports

    reported = "\n".join(errors)
    assert "'neither' must name either a 'port' or an 'interface'" in reported
    assert "'both' must name either a 'port' or an 'interface'" in reported
    assert "'unknown_key' says spin" in reported
    assert "'instance_alone' names an 'instance' of no 'interface'" in reported
    assert "'moveX' must be a number" in reported
    assert "only an assembly has nodes" in reported


def test_something_can_be_connected_through_a_port_an_enrich_mapped():
    """'lift' is the plate's 'handle', 5mm up; mating it to the base's 'handle'
    turns the lid over onto it, which puts the lid's origin 10mm up."""
    ctx = pc.init(PACKAGE)
    joined = ctx._get_assembly(":named_joined")
    asyncio.run(joined.do_instantiate())
    placed = {child.name: child for child in joined.connected_children() if child.name}
    assert tuple(placed["lid"].location.translation) == pytest.approx((0.0, 0.0, 10.0))
    assert placed["lid"].connection["to_port"] == "handle"


def test_a_key_that_is_not_text_is_reported_rather_than_raised(monkeypatch):
    from partcad import assembly_ports
    from partcad import logging as pc_logging

    errors = []
    monkeypatch.setattr(
        pc_logging, "error", lambda *args: errors.append(args[0] % args[1:] if len(args) > 1 else args[0])
    )
    assert assembly_ports.parse_entry("odd", {"port": "handle", 1: 2, "spin": 3}, "here") is None
    assert any("'odd' says 1, spin" in error for error in errors)
