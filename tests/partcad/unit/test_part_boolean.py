#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A 'boolean' part: two parts combined by 'and', 'or' or 'xor', by volume or by whole solids."""

import asyncio
import logging
import os
import sys
import textwrap

import pytest

import partcad as pc
from partcad import cmf

# 'partcad' before OCP: see the note in test_part_compound.py.
# isort: split

from OCP.BRep import BRep_Builder
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

PACKAGE = """
colors:
  red: "#C91A09"
  blue: "#0055BF"
materials:
  alu:
    density: 2700
  steel:
    density: 7850
parts:
  left:
    type: basic
    cuboid: 10
    parameters:
      color: {type: string, default: ":red"}
      material: {type: string, default: ":alu"}
  right:
    type: basic
    cuboid: 10
    offset: [[5, 0, 0], [0, 0, 1], 0]
    parameters:
      color: {type: string, default: ":blue"}
      material: {type: string, default: ":steel"}
  both:
    type: boolean
    operation: and
    parts: [left, right]
  either:
    type: boolean
    operation: or
    parts: [":left", ":right"]
  one-of:
    type: boolean
    operation: xor
    parts: [left, right]
  # Two boxes that touch, as a hub touches the bolts in it.
  pair:
    type: step
    path: pair.step
    parameters:
      material: {type: string, default: ":alu"}
  # Around the second cube, and over the last millimetre of the first.
  around-second:
    type: basic
    cuboid: [8, 12, 12]
    offset: [[13, 5, 5], [0, 0, 1], 0]
  second:
    type: boolean
    operation: and
    parts: [pair, around-second]
    whole: true
  second-by-volume:
    type: boolean
    operation: and
    parts: [pair, around-second]
  first:
    type: boolean
    operation: xor
    parts: [pair, second]
    whole: true
  wrong-operation:
    type: boolean
    operation: nand
    parts: [left, right]
  one-part:
    type: boolean
    operation: and
    parts: [left]
  whole-in-words:
    type: boolean
    operation: and
    parts: [left, right]
    whole: "yes"
  # Errors only building it can find.
  with-nothing:
    type: boolean
    operation: and
    parts: [left, nowhere]
  far:
    type: basic
    cuboid: 1
    offset: [[100, 0, 0], [0, 0, 1], 0]
  apart:
    type: boolean
    operation: and
    parts: [left, far]
  unreadable:
    type: step
    path: unreadable.step
  with-unreadable:
    type: boolean
    operation: and
    parts: [left, unreadable]
  uncached:
    type: basic
    cuboid: 10
    cache: false
  with-uncached:
    type: boolean
    operation: and
    parts: [left, uncached]
"""


def _write_pair(path):
    """A STEP file of two 10mm cubes side by side, touching along x = 10."""
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(10, 10, 10)).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(10, 0, 0), gp_Pnt(15, 10, 10)).Shape())
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    assert writer.Write(str(path))


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    path = tmp_path_factory.mktemp("boolean")
    (path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    _write_pair(path / "pair.step")
    (path / "unreadable.step").write_text("This is not a STEP file.\n")
    return pc.Context(str(path))


def _solids(shape) -> list:
    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), properties)
        found.append(round(properties.Mass(), 6))
        explorer.Next()
    return sorted(found)


def _built(ctx, name):
    part = ctx.get_part(":" + name)
    assert part is not None, name
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, name
    return part, ocp_serialize.decode_shape(envelope)


@pytest.mark.parametrize(
    "name, volumes",
    [
        # Two 10mm cubes, one 5mm to the side of the other.
        ("both", [500.0]),
        ("either", [1500.0]),
        ("one-of", [500.0, 500.0]),
    ],
)
def test_by_volume(ctx, name, volumes):
    _part, shape = _built(ctx, name)
    assert _solids(shape) == pytest.approx(volumes)


def _sets(part) -> list:
    summary = cmf.summary_of(part) or {}
    return summary.get("sets") or []


def test_what_both_occupy_is_made_of_the_first(ctx):
    part, _shape = _built(ctx, "both")
    sets = _sets(part)
    # The one solid is the first part's alu, and each face is in the colour of
    # the part it came from: the end the right cube's, and the first part's
    # where the two lay one on the other - the other five.
    assert {entry.get("material") for entry in sets} == {"//:alu"}
    faces = {entry.get("color"): entry["faces"] for entry in sets}
    assert faces == {"//:red": 5, "//:blue": 1}
    assert not (cmf.summary_of(part) or {}).get("unspecified")


def test_what_either_occupies_is_one_solid_of_the_first_s_material(ctx):
    part, _shape = _built(ctx, "either")
    assert {entry.get("material") for entry in _sets(part)} == {"//:alu"}


def test_what_only_one_occupies_is_made_of_that_one(ctx):
    part, _shape = _built(ctx, "one-of")
    by_material = {}
    for entry in _sets(part):
        by_material[entry.get("material")] = by_material.get(entry.get("material"), 0) + entry["solids"]
    assert by_material == {"//:alu": 1, "//:steel": 1}


def test_by_whole_solids_a_box_takes_one_piece_out_and_nothing_else(ctx):
    _part, shape = _built(ctx, "second")
    assert _solids(shape) == pytest.approx([500.0])
    # By volume, the same box cuts a slice off the first cube with it.
    _part, shape = _built(ctx, "second-by-volume")
    assert _solids(shape) == pytest.approx([100.0, 500.0])


def test_by_whole_solids_xor_puts_the_rest_back_without_it(ctx):
    part, shape = _built(ctx, "first")
    assert _solids(shape) == pytest.approx([1000.0])
    assert {entry.get("material") for entry in _sets(part)} == {"//:alu"}


@pytest.mark.parametrize(
    "name, message", [("wrong-operation", "'operation'"), ("one-part", "'parts'"), ("whole-in-words", "'whole'")]
)
def test_a_declaration_that_is_not_one_says_why(ctx, caplog, name, message):
    with caplog.at_level(logging.ERROR):
        assert ctx.get_part(":" + name) is None
    assert any(message in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "name, message",
    [
        ("with-nothing", "the part //:nowhere is not found"),
        ("apart", "leaves no solid"),
        ("with-unreadable", "with-unreadable: failed to combine the two parts"),
    ],
)
def test_a_boolean_that_cannot_be_built_says_why(ctx, caplog, name, message):
    part = ctx.get_part(":" + name)
    assert part is not None
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(part.get_wrapped(ctx)) is None
    assert any(message in record.getMessage() for record in caplog.records), [r.getMessage() for r in caplog.records]


def test_what_is_built_of_a_part_that_is_not_cached_is_not_cached_either(ctx):
    part = ctx.get_part(":with-uncached")
    asyncio.run(part.get_cache_key_async())
    assert part.cacheable is False


def test_two_operations_on_the_same_parts_are_two_entries(ctx):
    keys = {asyncio.run(ctx.get_part(":" + name).get_cache_key_async()) for name in ("both", "either", "one-of")}
    assert len(keys) == 3


def test_the_schema_takes_a_boolean_and_refuses_another_operation():
    import jsonschema
    import yaml

    from partcad.lint.all import get_partcad_schema

    schema = get_partcad_schema()
    document = yaml.safe_load(textwrap.dedent(PACKAGE))
    for name in ("wrong-operation", "one-part", "whole-in-words"):
        broken = {"parts": {name: document["parts"].pop(name)}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)
    jsonschema.validate(document, schema)
