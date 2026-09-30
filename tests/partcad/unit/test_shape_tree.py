#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape's tree holds, whatever kind of shape it is.

One representation for every subject: a part or a sketch is a tree one node deep,
an assembly is a node per thing it holds, an interface is a node per port, and
every node carries its geometry, where it sits, and what it declares about
connections. See 'partcad.shape_envelope' for the node and
'partcad.shape_gltf' for the other form of it.

None of this builds geometry or tessellates anything: where a node sits is
'geom.Location' algebra over plain data, and the ports are read out of the
declarations. See 'viewer_fakes' for the objects.
"""

import asyncio

import pytest
from viewer_fakes import fake_assembly, fake_interface, fake_part, fake_port, fake_sketch, placed

from partcad import shape_envelope, shape_ports
from partcad.geom import Location

CTX = object()

SOMEWHERE = [[0.0, 0.0, 20.0], [0.0, 0.0, 1.0], 0.0]


def _tree(shape):
    return asyncio.run(shape.get_representation(CTX, shape_envelope.FORM_BREP))


def _children(node):
    return node.get(shape_envelope.KEY_ASSEMBLY) or []


def _ports(node):
    return node.get(shape_envelope.KEY_PORTS) or []


def _interfaces(node):
    return node.get(shape_envelope.KEY_INTERFACES) or []


def _translation(packed):
    return tuple(Location(packed).translation)


#
# A part, and a sketch: the same tree, one node deep.
#


def test_a_part_is_one_node_carrying_its_geometry():
    part = fake_part("cube")
    node = _tree(part)

    assert node["name"] == "//pkg:cube"
    assert node[shape_envelope.KEY_BREP] == "..."
    # Depth one: nothing inside it, and nothing about that is a special case.
    assert shape_envelope.KEY_ASSEMBLY not in node
    assert _ports(node) == []
    assert shape_envelope.is_node(node)


def test_a_part_carries_its_ports_and_the_interfaces_they_form():
    where = Location([[1.0, 2.0, 3.0], [0.0, 0.0, 1.0], 90.0])
    part = fake_part(
        "bracket",
        ports={
            "thru-m3": fake_port(where, sketch=fake_sketch("m3")),
            "grip": fake_port(),
        },
        interfaces={"//pkg:m3-thru": {"": {"thru": "thru-m3"}}},
    )
    node = _tree(part)

    # In the frame of the object that declares them: a node's own location places
    # its ports along with its geometry, so a port is stated once, where it was.
    assert _ports(node) == [
        {
            "name": "thru-m3",
            shape_envelope.KEY_LOCATION: where.as_packed(),
            "interface": "//pkg:m3-thru",
            "instance": "",
            # The reference and not the geometry: reading a declaration is a
            # lookup and building a sketch is not.
            "sketch": "//pkg:m3",
        },
        {"name": "grip", shape_envelope.KEY_LOCATION: Location().as_packed()},
    ]
    assert _interfaces(node) == [{"name": "//pkg:m3-thru", "instance": "", "ports": ["thru-m3"]}]


def test_the_ports_are_partitioned_between_the_interfaces_and_the_rest():
    """Every port belongs to exactly one interface instance, or to none.

    Which is what lets a reader of the tree list each port once: an interface
    names the ports it is made of, and what no interface named is what is left.
    """
    part = fake_part(
        "plate",
        ports={"top-m3": fake_port(), "bottom-m3": fake_port(), "grip": fake_port()},
        interfaces={
            "//pkg:m3-thru": {"top": {"thru": "top-m3"}, "bottom": {"thru": "bottom-m3"}},
        },
    )
    node = _tree(part)

    named = [port for entry in _interfaces(node) for port in entry["ports"]]
    assert sorted(named) == ["bottom-m3", "top-m3"]
    assert len(named) == len(set(named))
    assert [port["name"] for port in _ports(node)] == ["top-m3", "bottom-m3", "grip"]
    assert [entry["instance"] for entry in _interfaces(node)] == ["top", "bottom"]


def test_a_shape_with_no_ports_says_nothing_about_connections():
    """Which is most shapes, and they must not pay a key for it."""
    node = _tree(fake_part("cube"))
    assert shape_envelope.KEY_PORTS not in node
    assert shape_envelope.KEY_INTERFACES not in node


#
# An assembly: the hierarchy it is instantiated as.
#


def _mount():
    """Two plates, one 20mm above the other, each with a port; one externalized."""
    lower = fake_part("plate", ports={"handle": fake_port(Location([[0, 0, 5], [0, 0, 1], 0]))})
    upper = fake_part("plate", ports={"handle": fake_port(Location([[0, 0, 5], [0, 0, 1], 0]))})
    return fake_assembly(
        "mount",
        children=[placed(lower, "lower"), placed(upper, "upper", SOMEWHERE)],
        ports={"hold": fake_port(Location([[0, 0, 5], [0, 0, 1], 0]))},
    )


def test_an_assembly_is_a_node_per_thing_it_holds():
    node = _tree(_mount())

    assert node["name"] == "//pkg:mount"
    assert [child["label"] for child in _children(node)] == ["lower", "upper"]
    # The node it holds keeps its own geometry and takes this assembly's account
    # of what it is called and where it sits.
    lower, upper = _children(node)
    assert lower["name"] == "//pkg:plate"
    assert shape_envelope.KEY_LOCATION not in lower
    assert _translation(upper[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 20.0))


def test_every_node_of_an_assembly_carries_its_own_ports():
    node = _tree(_mount())

    # The assembly's own - what its 'map:' externalizes and what it declares.
    assert [port["name"] for port in _ports(node)] == ["hold"]
    for child in _children(node):
        assert [port["name"] for port in _ports(child)] == ["handle"]
        # Stated in the child's own frame, not moved into the assembly's: the
        # node's location is what places them, exactly as it places its geometry.
        assert _translation(_ports(child)[0][shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 5.0))


def test_an_assemblys_own_location_places_what_is_inside_it():
    plate = fake_part("plate")
    node = _tree(fake_assembly("raised", children=[placed(plate, "bottom")], location=[[0, 0, 100], [0, 0, 1], 0]))

    # Carried on the assembly's node rather than pushed down into its children:
    # one placement, applied where the tree is drawn or realized.
    assert _translation(node[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 100.0))
    assert shape_envelope.KEY_LOCATION not in _children(node)[0]


def test_an_embedded_links_assembly_is_a_node_like_any_other():
    """The tree is the one an assembly is instantiated as, and that is one of its nodes.

    An ASSY file's 'links:' becomes an assembly of its own inside the object the
    file defines. It is no object of any package and nobody names it in a
    'connect:', but it is there, it holds a placement, and a reader of the tree
    sees what the file wrote.
    """
    plate = fake_part("plate")
    group = fake_assembly(
        "outer:links", children=[placed(plate, "inner")], location=[[0, 0, 7], [0, 0, 1], 0], child=True
    )
    node = _tree(fake_assembly("outer", children=[placed(group, None)]))

    (container,) = _children(node)
    assert container["label"] == "outer:links"
    assert _translation(container[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 7.0))
    assert [child["label"] for child in _children(container)] == ["inner"]


#
# An interface: an assembly of the sketches its ports are drawn with.
#


def test_an_interface_is_its_ports_and_the_sketches_they_are_drawn_with():
    where = Location([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0])
    interface = fake_interface("m3-thru", ports={"thru": fake_port(where, sketch=fake_sketch("m3"))})
    node = _tree(interface)

    assert node["name"] == "//pkg:m3-thru"
    # Its ports are on the interface node, which is where a node's own ports live
    # whatever kind of node it is, and each names the sketch it is drawn with.
    (port,) = _ports(node)
    assert (port["name"], port["sketch"]) == ("thru", "//pkg:m3")
    assert _translation(port[shape_envelope.KEY_LOCATION]) == pytest.approx((1.0, 0.0, 0.0))
    # No node of its own for that sketch: a port is drawn where it is, with what it
    # names, and a node would be the same sketch under a second checkbox.
    assert _children(node) == []


def test_an_interface_holds_what_it_inherits_as_a_sub_assembly():
    opening = fake_interface("m3-opening", ports={"opening": fake_port(sketch=fake_sketch("m3"))})
    thru = fake_interface(
        "m3-thru",
        ports={"thru": fake_port()},
        parents={"m3-opening": (opening, {"thru": Location([[0, 0, 3], [0, 0, 1], 0])})},
    )
    node = _tree(thru)

    (parent,) = _children(node)
    assert parent["name"] == "//pkg:m3-opening"
    assert parent["label"] == "thru"
    assert _translation(parent[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 3.0))
    # The whole of it, recursively: its own ports are inside, each naming what it
    # is drawn with.
    (port,) = _ports(parent)
    assert (port["name"], port["sketch"]) == ("opening", "//pkg:m3")


def test_an_interface_that_inherits_itself_stops_rather_than_recursing():
    """A cycle is a broken package, and a stack overflow reports nothing about it."""
    looping = fake_interface("loop", ports={"p": fake_port()})
    looping.inherits = {}
    node_of = fake_interface("outer", ports={"q": fake_port()}, parents={"loop": (looping, {"": Location()})})
    # The parent points back at the interface doing the inheriting.
    from partcad.interface_inherit import InterfaceInherits

    back = InterfaceInherits.__new__(InterfaceInherits)
    back.interface = node_of
    back.instances = {"": Location()}
    looping.inherits = {"outer": back}

    node = _tree(node_of)
    (parent,) = [child for child in _children(node) if shape_envelope.KEY_ASSEMBLY in child]
    assert parent["name"] == "//pkg:loop"
    # 'outer' is not put inside 'loop' a second time.
    assert [child for child in _children(parent) if shape_envelope.KEY_ASSEMBLY in child] == []


#
# The sketches the ports are drawn with.
#


def test_the_sketches_the_ports_are_drawn_with_come_with_the_representation():
    """A port is a frame; most ports are also drawn with the shape of the opening.

    The node records the reference - reading a declaration is a lookup, building a
    sketch is not - and the geometry is attached to the root, once per sketch.
    """
    part = fake_part(
        "bracket",
        ports={"a": fake_port(sketch=fake_sketch("m3")), "b": fake_port(sketch=fake_sketch("m3"))},
    )

    class FakeContext:
        def get_sketch(self, reference):
            assert reference == "//pkg:m3"
            return fake_sketch("m3")

    tree = asyncio.run(part.get_representation(FakeContext(), shape_envelope.FORM_BREP))

    # Two ports, one sketch: what travels is one copy, keyed by what they name.
    assert [port["sketch"] for port in _ports(tree)] == ["//pkg:m3", "//pkg:m3"]
    sketches = tree[shape_envelope.KEY_SKETCHES]
    assert list(sketches) == ["//pkg:m3"]
    assert sketches["//pkg:m3"]["brep"] == "..."


def test_a_shape_whose_ports_draw_with_nothing_carries_no_sketches():
    """Which is every port declared by name alone, and most shapes."""
    tree = _tree(fake_part("cube", ports={"grip": fake_port()}))
    assert shape_envelope.KEY_SKETCHES not in tree


def test_a_sketch_that_will_not_resolve_costs_that_port_its_boundary_and_no_more():
    """The frame is still drawn, and the frame is the half that says where it is."""
    part = fake_part("bracket", ports={"a": fake_port(sketch=fake_sketch("missing"))})

    class FakeContext:
        def get_sketch(self, reference):
            raise Exception("no such package")

    tree = asyncio.run(part.get_representation(FakeContext(), shape_envelope.FORM_BREP))
    assert shape_envelope.KEY_SKETCHES not in tree
    assert [port["name"] for port in _ports(tree)] == ["a"]


def test_attaching_the_sketches_does_not_touch_what_the_cache_holds():
    """The tree handed in may be the very object a cache is holding."""
    from partcad import port_sketches

    cached = {"brep": "...", shape_envelope.KEY_PORTS: [{"name": "a", "sketch": "//pkg:m3"}]}

    class FakeContext:
        def get_sketch(self, reference):
            return fake_sketch("m3")

    attached = asyncio.run(port_sketches.attach_async(FakeContext(), cached))
    assert shape_envelope.KEY_SKETCHES in attached
    assert shape_envelope.KEY_SKETCHES not in cached


#
# The two forms, and the composition every node's placement goes through.
#


def test_the_form_decides_the_payload_and_nothing_about_the_tree(monkeypatch):
    from partcad import shape_gltf

    asked = {}

    async def fake_convert(ctx, tree, **kwargs):
        asked["tree"] = tree
        return {"name": tree["name"], shape_envelope.KEY_GLTF: "tessellated"}

    monkeypatch.setattr(shape_gltf, "convert_async", fake_convert)

    part = fake_part("cube")
    brep = _tree(part)
    gltf = asyncio.run(part.get_representation(CTX, shape_envelope.FORM_GLTF))

    # The same tree goes to the sandbox; only what sits at its nodes comes back
    # different.
    assert asked["tree"] == brep
    assert gltf[shape_envelope.KEY_GLTF] == "tessellated"


def test_an_unknown_form_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        asyncio.run(fake_part("cube").get_representation(CTX, "step"))


def test_placing_a_node_composes_onto_what_it_already_carried():
    inner = {"brep": "...", shape_envelope.KEY_LOCATION: [[0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 0.0]}
    moved = shape_envelope.placed(inner, Location([[0.0, 0.0, 20.0], [0.0, 0.0, 1.0], 0.0]), label="upper")

    assert _translation(moved[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 25.0))
    assert moved["label"] == "upper"
    # The node handed in is not touched: a cached payload is shared.
    assert _translation(inner[shape_envelope.KEY_LOCATION]) == pytest.approx((0.0, 0.0, 5.0))


def test_a_node_nothing_placed_carries_no_placement():
    """So that an envelope nothing moved travels exactly as it was cached."""
    inner = {"brep": "..."}
    assert shape_envelope.placed(inner, None, label="x") == {"brep": "...", "label": "x"}


#
# The connection layer is re-stamped rather than cached, like the name beside it.
#


def test_the_connection_layer_is_part_of_what_a_shape_stamps_on_its_payload():
    """A cache entry is keyed on geometry and shared by every shape whose geometry
    is identical, so where this shape's ports are has to be re-applied every time
    a payload is materialized - exactly as its name and its properties are."""
    part = fake_part("bracket", ports={"grip": fake_port()})
    metadata = part.get_cache_metadata()

    assert metadata["name"] == "//pkg:bracket"
    assert [port["name"] for port in metadata[shape_envelope.KEY_PORTS]] == ["grip"]

    # And that is what 'apply_metadata' puts back around a payload read from a
    # cache, which is the path a shape that was not rebuilt takes.
    wrapped = shape_envelope.apply_metadata({"brep": "..."}, metadata)
    assert [port["name"] for port in wrapped[shape_envelope.KEY_PORTS]] == ["grip"]


def test_an_interface_answers_for_its_own_ports():
    """A shape's ports are its 'with_ports'; an interface's are its own."""
    interface = fake_interface("m3", ports={"m3": fake_port()})
    assert shape_ports.port_carrier(interface) is interface
    # And reporting an interface as the interface of its own ports would say
    # nothing, so it does not.
    assert shape_ports.interface_of_port(interface) == {}
    assert [record.interface for record in shape_ports.own_ports(interface)] == [None]
