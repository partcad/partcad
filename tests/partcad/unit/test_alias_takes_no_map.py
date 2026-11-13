#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An alias takes no 'map:', of any kind of object: an enrich of the same 'source' does.

An alias is the object it names under another name and nothing more. Names of
its own for what that object has are a declaration of what the object is to this
package, which is what an enrich is - and an enrich with no 'with:' is the same
object, so its 'map:' means what an alias's used to.
"""

import textwrap

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad.lint.all import get_partcad_schema
from partcad.project import ALIAS_TAKES_NO_MAP

PACKAGE = """
sketches:
  circle:
    type: basic
    circle: 1.5
  circle-alias:
    type: alias
    source: circle
    map:
      rim: [edge]
parts:
  plate:
    type: step
    path: plate.step
    ports:
      top: [[0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 0.0]
  plate-alias:
    type: alias
    source: plate
    map:
      lid: [top]
  plate-enrich:
    type: enrich
    source: plate
    map:
      lid: [top]
  plate-renamed:
    type: alias
    source: plate
assemblies:
  stack:
    type: assy
  stack-alias:
    type: alias
    source: stack
    map:
      lid: [plate, top]
  stack-enrich:
    type: enrich
    source: stack
    map:
      lid: [plate, top]
scenes:
  room:
    type: assy
  room-alias:
    type: alias
    source: room
    map:
      lid: [plate, top]
"""

ASSY = """
links:
  - part: plate
    name: plate
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    (tmp_path / "plate.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    (tmp_path / "stack.assy").write_text(textwrap.dedent(ASSY))
    (tmp_path / "room.assy").write_text(textwrap.dedent(ASSY))
    pc.logging.reset_errors()
    try:
        yield pc.Context(str(tmp_path))
    finally:
        pc.logging.reset_errors()


GETTERS = {
    "sketch": "get_sketch",
    "part": "get_part",
    "assembly": "get_assembly",
    "scene": "get_scene",
}


@pytest.mark.parametrize(
    "kind, name",
    [("sketch", "circle-alias"), ("part", "plate-alias"), ("assembly", "stack-alias"), ("scene", "room-alias")],
)
def test_an_alias_with_a_map_is_refused_whatever_it_names(ctx, kind, name):
    found = getattr(ctx, GETTERS[kind])(":" + name)

    assert found is None
    reason = ctx.get_project("//").get_broken_object_reason(kind, name)
    assert reason == ALIAS_TAKES_NO_MAP
    assert "'type: enrich'" in reason
    assert pc.logging.had_errors is True


@pytest.mark.parametrize("kind, name", [("part", "plate-enrich"), ("assembly", "stack-enrich")])
def test_an_enrich_with_the_same_map_is_created(ctx, kind, name):
    assert getattr(ctx, GETTERS[kind])(":" + name) is not None
    assert ctx.get_project("//").get_broken_object_reason(kind, name) is None


def test_an_alias_without_a_map_is_still_an_alias(ctx):
    assert ctx.get_part(":plate-renamed") is not None
    assert ctx.get_project("//").get_broken_object_reason("part", "plate-renamed") is None


@pytest.mark.parametrize(
    "document",
    [
        {"parts": {"a": {"type": "alias", "source": "b", "map": {"lid": ["top"]}}}},
        {"assemblies": {"a": {"type": "alias", "source": "b", "map": {"lid": ["plate", "top"]}}}},
    ],
)
def test_the_schema_refuses_a_map_on_an_alias(document):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, get_partcad_schema())


@pytest.mark.parametrize(
    "document",
    [
        {"parts": {"a": {"type": "enrich", "source": "b", "map": {"lid": ["top"]}}}},
        {"assemblies": {"a": {"type": "enrich", "source": "b", "map": {"lid": ["plate", "top"]}}}},
        {"parts": {"a": {"type": "alias", "source": "b"}}},
        {"assemblies": {"a": {"type": "assy", "map": {"lid": ["plate", "top"]}}}},
    ],
)
def test_the_schema_takes_a_map_everywhere_else(document):
    jsonschema.validate(document, get_partcad_schema())


def test_the_whole_package_lints_as_refused():
    """The package above as 'pc lint' and the editor read it: refused for its aliases' maps alone."""
    document = yaml.safe_load(textwrap.dedent(PACKAGE))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, get_partcad_schema())
    for kind in ("parts", "assemblies"):
        for name in list(document[kind]):
            if document[kind][name].get("type") == "alias":
                document[kind][name].pop("map", None)
    document["sketches"]["circle-alias"].pop("map")
    document["scenes"]["room-alias"].pop("map")
    jsonschema.validate(document, get_partcad_schema())
