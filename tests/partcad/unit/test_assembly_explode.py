#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for exploded views: an ASSY assembly's 'exploded' parameter, and the book's steps.

Where an item goes when an assembly is pulled apart is one rule
('partcad.assembly_explode'), asked by an assembly declared 'exploded: true'
and by an instruction book's step. The first is an object-type parameter of the
'assy' type, so 'stack;exploded=true' is an object with a key of its own; the
second is keyed on the assembly the step is of and the step.

No sandbox: geometry is stubbed where it would be built or measured.
"""

import asyncio
import textwrap
import types

import pytest

import partcad as pc
from partcad import assembly_explode, assembly_guide, shape_envelope, shape_ports
from partcad.geom import Location

PACKAGE = textwrap.dedent("""
    name: //explode
    parts:
      block:
        type: step
        path: block.step
        ports:
          top: [[5.0, 5.0, 10.0], [0.0, 0.0, 1.0], 0.0]
    assemblies:
      stack:
        type: assy
        map:
          lid-top: [lid, top]
      stack_exploded:
        type: alias
        source: :stack
        with:
          exploded: true
      imported:
        type: step
        path: block.step
        parameters:
          exploded:
            type: bool
            default: true
    """)

STACK = textwrap.dedent("""
    links:
      - part: block
        name: base
      - part: block
        name: lid
        location: [[0, 0, 10], [0, 0, 1], 0]
      - part: block
        name: cap
        location: [[0, 0, 20], [0, 0, 1], 0]
    """)

# Every block is a 10 mm cube with a corner at its own origin.
BOX = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "stack.assy").write_text(STACK)
    (tmp_path / "block.step").write_text("ISO-10303-21; block")

    async def get_wrapped(self, _ctx):
        return {"brep": b"block"}

    async def get_bounding_box_async(self, _ctx):
        return BOX

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    monkeypatch.setattr(pc.shape.Shape, "get_bounding_box_async", get_bounding_box_async)
    return pc.Context(str(tmp_path))


def _run(coroutine):
    return asyncio.run(coroutine)


def _instantiated(ctx, name):
    assembly = ctx.get_assembly(name)
    assert assembly is not None
    _run(assembly.do_instantiate())
    return assembly


# --------------------------------------------------------------------------- #
# Where each item goes                                                        #
# --------------------------------------------------------------------------- #


class _Item:
    """A shape of a known size, for the rule alone."""

    def __init__(self, box=BOX):
        self.box = box

    async def get_bounding_box_async(self, _ctx):
        return self.box

    async def get_max_dimension_async(self, _ctx):
        return max(self.box[3] - self.box[0], self.box[4] - self.box[1], self.box[5] - self.box[2])


def _child(name, location=None, **connection):
    return types.SimpleNamespace(
        name=name, item=_Item(), location=location or Location(), connection=connection or None
    )


def test_the_moves_add_up_along_the_connections():
    """A bolt in a bracket pulled off a frame goes with the bracket, and then out of it."""
    frame = _child("frame")
    bracket = _child("bracket", target="frame", direction=[0, 0, 1], exploded=5)
    bolt = _child("bolt", Location([[1, 0, 0], [0, 0, 1], 0]), target="bracket", direction=[1, 0, 0], exploded=3)
    assembly = types.SimpleNamespace(children=[frame, bracket, bolt], name="machine")

    offsets = _run(assembly_explode.offsets_async(None, assembly))

    assert offsets == [(0.0, 0.0, 0.0), (0.0, 0.0, 5.0), (3.0, 0.0, 5.0)]


def test_an_item_backs_out_of_what_it_is_joined_to_not_into_it():
    """A port's normal is an axis: the end that points away from the other item is taken."""
    base = _child("base")
    lid = _child("lid", Location([[0, 0, 10], [0, 0, 1], 0]), target="base", direction=[0, 0, -1])

    found = _run(
        assembly_explode.separation_async(None, lid.item, lid.location, base.item, base.location, lid.connection)
    )

    assert found.direction == (0.0, 0.0, 1.0)
    # Half of the larger of the two, said nowhere else.
    assert found.distance == assembly_explode.EXPLODED_FRACTION * 10.0


# --------------------------------------------------------------------------- #
# 'exploded' on an ASSY assembly                                              #
# --------------------------------------------------------------------------- #


def test_an_assembly_is_not_exploded_unless_it_says_so(ctx):
    assert _instantiated(ctx, "//explode:stack").exploded is False
    assert _instantiated(ctx, "//explode:stack;exploded=true").exploded is True


def test_exploded_is_part_of_what_the_assembly_is_cached_under(ctx):
    plain = ctx.get_assembly("//explode:stack")
    exploded = ctx.get_assembly("//explode:stack;exploded=true")

    assert _run(plain.get_cache_key_async()) != _run(exploded.get_cache_key_async())
    # And nothing about it is in the key of an assembly that never mentions
    # it: the type's default is applied when it is read, never written down.
    assert "parameters" not in plain.config


def test_an_exploded_view_can_have_a_name_of_its_own(ctx):
    """An alias with 'with: exploded: true' is that view, and is cached as it."""
    named = ctx.get_assembly("//explode:stack_exploded")
    exploded = ctx.get_assembly("//explode:stack;exploded=true")

    assert _run(named.get_cache_key_async()) == _run(exploded.get_cache_key_async())


def test_an_exploded_assembly_moves_each_item_out_of_what_it_is_joined_to(ctx):
    plain = _instantiated(ctx, "//explode:stack")
    exploded = _instantiated(ctx, "//explode:stack;exploded=true")

    def heights(assembly):
        tree = _run(assembly._get_shape_real(ctx))
        return [Location(node[shape_envelope.KEY_LOCATION]).as_packed()[0][2] for node in tree["assembly"]]

    assert heights(plain) == [0.0, 10.0, 20.0]
    # Upwards, the way they were stacked: the lid backs out of the base by half
    # a block, and the cap out of the two together - by half of those two, which
    # are two blocks tall - from where they were assembled.
    assert heights(exploded) == [0.0, 15.0, 30.0]


def test_a_port_inside_an_exploded_assembly_is_where_its_item_is_drawn(ctx):
    """'--with-internals' draws the ports of the items, on the items."""

    def heights(name):
        assembly = _instantiated(ctx, name)
        records = _run(shape_ports.ports_async(assembly, ctx, deep=True))
        return {record.name: record.location.as_packed()[0][2] for record in records if record.owner}

    assert heights("//explode:stack") == {"base:top": 10.0, "lid:top": 20.0, "cap:top": 30.0}
    assert heights("//explode:stack;exploded=true") == {"base:top": 10.0, "lid:top": 25.0, "cap:top": 40.0}


def test_a_port_an_exploded_assembly_maps_is_on_its_item_where_it_is_drawn(ctx):
    """A 'map:' port is drawn by '--with-ports', and is where a 'connect:' to the assembly meets it."""

    def height(name):
        assembly = _instantiated(ctx, name)
        records = _run(shape_ports.ports_async(assembly, ctx))
        return {record.name: record.location.as_packed()[0][2] for record in records}["lid-top"]

    assert height("//explode:stack") == 20.0
    assert height("//explode:stack;exploded=true") == 25.0


def test_an_exploded_assembly_s_box_is_around_its_items_where_they_are_drawn(ctx):
    assert _run(_instantiated(ctx, "//explode:stack").get_bounding_box_async(ctx)) == (0, 0, 0, 10, 10, 30)
    assert _run(_instantiated(ctx, "//explode:stack;exploded=true").get_bounding_box_async(ctx)) == (
        0,
        0,
        0,
        10,
        10,
        40,
    )


def test_an_item_that_is_an_assembly_moves_as_one_piece(tmp_path, monkeypatch, ctx):
    """Exploding stops at the assembly's own items: what is inside one stays where it was in it."""
    (tmp_path / "tower.assy").write_text(textwrap.dedent("""
            links:
              - part: block
                name: plinth
              - assembly: stack
                name: column
                location: [[0, 0, 10], [0, 0, 1], 0]
            """))
    package = (tmp_path / "partcad.yaml").read_text()
    (tmp_path / "partcad.yaml").write_text(package + "  tower:\n    type: assy\n")
    ctx = pc.Context(str(tmp_path))

    tower = _instantiated(ctx, "//explode:tower;exploded=true")
    records = _run(shape_ports.ports_async(tower, ctx, deep=True))
    heights = {record.name: record.location.as_packed()[0][2] for record in records if record.owner}

    # The column backs out of the plinth by half of the larger of the two - the
    # column, three blocks tall - and its blocks stay stacked inside it, the
    # port it maps of its lid with them.
    assert heights == {
        "plinth:top": 10.0,
        "column:lid-top": 45.0,
        "column:base:top": 35.0,
        "column:lid:top": 45.0,
        "column:cap:top": 55.0,
    }


def test_a_type_that_cannot_explode_refuses_to_be_asked(ctx):
    """An assembly read from a STEP file holds geometry, not what is joined to what."""
    assert ctx.get_assembly("//explode:imported") is None


# --------------------------------------------------------------------------- #
# The pictures of an instruction book                                         #
# --------------------------------------------------------------------------- #


def _section(ctx, monkeypatch, name="//explode:stack"):
    async def straight_up(_ctx, step):
        step.direction = (0.0, 0.0, 1.0)
        step.distance = 5.0

    monkeypatch.setattr(assembly_guide, "_resolve_step_geometry", straight_up)
    stack = _instantiated(ctx, name)
    return stack, _run(assembly_guide._build_section(ctx, stack))


def test_a_step_picture_is_keyed_on_the_assembly_and_the_step(ctx, monkeypatch):
    stack, section = _section(ctx, monkeypatch)
    key = _run(stack.get_cache_key_async())
    first, second = section.steps
    colors = "colors=%s,%s" % (assembly_guide.CONTEXT_COLOR, assembly_guide.NEW_COLOR)

    assert _run(assembly_guide.exploded_assembly(section, first).get_artifact_key_async()) == (
        "%s#guide-step-1-exploded;direction=0.0,0.0,1.0;distance=5.0;%s" % (key, colors)
    )
    # What is there already when the second step is done - the base and the
    # lid - is the assembly's and the step's to say, and in the key that way.
    assert _run(assembly_guide.exploded_assembly(section, second).get_artifact_key_async()) == (
        "%s#guide-step-2-exploded;direction=0.0,0.0,1.0;distance=5.0;%s" % (key, colors)
    )


def test_the_picture_of_fastening_a_step_is_keyed_on_where_its_fasteners_are_pulled_to(ctx, monkeypatch):
    stack, section = _section(ctx, monkeypatch)
    key = _run(stack.get_cache_key_async())
    step = section.steps[0]
    step.fasteners = [
        assembly_guide.GuideFastener(
            item=step.item, item_name="screw", location=Location(), direction=(1.0, 0.0, 0.0), distance=12.5
        )
    ]

    assert _run(assembly_guide.fastened_assembly(section, step).get_artifact_key_async()) == (
        "%s#guide-step-1-fastened;direction=1.0,0.0,0.0;distance=12.5;colors=%s,%s"
        % (key, assembly_guide.CONTEXT_COLOR, assembly_guide.NEW_COLOR)
    )


def test_a_book_drawn_again_asks_for_the_same_pictures(ctx, monkeypatch):
    _stack, section = _section(ctx, monkeypatch)
    _again, again = _section(ctx, monkeypatch)

    for step, same in zip(section.steps, again.steps):
        assert _run(assembly_guide.exploded_assembly(section, step).get_artifact_key_async()) == _run(
            assembly_guide.exploded_assembly(again, same).get_artifact_key_async()
        )


def test_the_book_of_an_assembly_that_is_not_cached_is_drawn_every_time(ctx, monkeypatch):
    stack, section = _section(ctx, monkeypatch)
    monkeypatch.setattr(stack, "cacheable", False)

    for step in section.steps:
        assert _run(assembly_guide.exploded_assembly(section, step).get_artifact_key_async()) is None
