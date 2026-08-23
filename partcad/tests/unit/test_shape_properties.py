#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape reports about itself, from the configuration to the exporter.

'parameters:' are inputs - a request made of the object type that produces the
shape. 'properties:' are outputs - what the instantiated shape turns out to be.
This file follows one of those outputs the whole way: onto the envelope, through
the shape cache, through the composition of an assembly, and into the index an
export implementation looks it up in.

Everything here is pure Python: envelopes, JSON and dicts. No CAD kernel and no
sandbox is involved, which is the point - the properties travel as data beside
the geometry rather than being collected from the object graph.
"""

import asyncio
import json
import os
import sys

import jsonschema
import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import shape_envelope
from partcad.assembly import Assembly
from partcad.cache_hash import CacheHash
from partcad.cache_shape import ShapeCache
from partcad.lint.all import get_partcad_schema
from partcad.shape import Shape

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_export  # noqa: E402

# Not a real BREP, but it starts the way an uncompressed payload does, which is
# all the cache uses to tell a raw payload from a JSON one.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"

STEEL = {"material": "steel", "color": "#8899AA"}
BRASS = {"material": "brass", "physics": {"mass": 0.25}}


def _cache(tmp_path):
    return ShapeCache(user_config=CacheUserConfig(tmp_path))


def _hash():
    cache_hash = CacheHash("geometry", cache=True)
    # Every shape below builds the same geometry, and so shares one entry.
    cache_hash.add_string("identical-geometry")
    return cache_hash


class _Ctx:
    def __init__(self, tmp_path):
        self.cache_shapes = _cache(tmp_path)


class _Part(Shape):
    """A part whose factory hands back an envelope, with no sandbox involved."""

    def __init__(self, name, properties=None):
        config = {"name": name}
        if properties is not None:
            config["properties"] = properties
        super().__init__("pkg", config)
        self.name = name
        self.kind = "part"
        self.hash.add_string("identical-geometry")

    async def get_shape(self, ctx):
        return {"name": None, "label": None, "brep": BREP}


class _Assembly(Assembly):
    def __init__(self, name, properties=None, child_properties=None):
        config = {"name": name}
        if properties is not None:
            config["properties"] = properties
        super().__init__("pkg", config)
        self.name = name
        self.hash.add_string("identical-geometry")
        self._child_properties = child_properties

    def instantiate(self, _assembly):
        child = _Part("leaf", self._child_properties)
        child.cacheable = False
        self.add(child, name="leaf")


# The configuration says it, and the schema agrees
# ------------------------------------------------


def _validate(config):
    jsonschema.validate(instance=config, schema=get_partcad_schema())


def test_the_schema_takes_the_properties_section_on_a_part_and_on_an_assembly():
    _validate(
        {
            "parts": {"bolt": {"type": "step", "properties": dict(STEEL, physics={"mass": 0.01})}},
            "assemblies": {"rig": {"type": "assy", "properties": {"material": "steel"}}},
        }
    )


def test_the_schema_refuses_the_flat_form_and_an_unknown_property():
    """Where these used to sit, and what keeps the set of them closed."""
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate({"parts": {"bolt": {"type": "step", "material": "steel"}}})
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate({"parts": {"bolt": {"type": "step", "properties": {"smell": "burnt"}}}})


# What a connection costs, which an interface states and a shape must not: these
# describe moving a joint, not being a body. Values of the type each is declared
# with, so that a rejection below is about the name and nothing else.
CONNECTION_ONLY_PHYSICS = {
    "maxEffort": 12.0,
    "maxVelocity": 30.0,
    "damping": 0.5,
    "springStiffness": 100.0,
    "springReference": 0.0,
    "stopCfm": 0.1,
    "stopErp": 0.2,
    "fudgeFactor": 0.5,
    "implicitSpringDamper": True,
    "provideFeedback": True,
}


def _errors(config):
    """Every error raised for 'config', including those nested inside a 'oneOf'.

    'parts' and 'assemblies' are each wrapped in one, so the best-match error
    names the 'oneOf' and the error that names the offending property sits
    underneath it in '.context'. Draft 7 explicitly because that is what
    '$schema' says: a later validator reads this schema's tuple-form 'items' as
    a single subschema and misjudges the OCCT locations.
    """
    validator = jsonschema.Draft7Validator(get_partcad_schema())

    def walk(errors):
        for error in errors:
            yield error
            yield from walk(error.context or [])

    return list(walk(validator.iter_errors(config)))


def test_the_schema_takes_a_body_property_on_a_shape():
    """What a body is: mass, where it balances, how it rubs and how it bounces."""
    _validate({"parts": {"bolt": {"type": "step", "properties": {"physics": {"mass": 0.01, "friction": 0.4}}}}})
    _validate({"assemblies": {"rig": {"type": "assy", "properties": {"physics": {"restitution": 0.2}}}}})


@pytest.mark.parametrize("name,value", sorted(CONNECTION_ONLY_PHYSICS.items()))
@pytest.mark.parametrize("kind,declaration", [("parts", {"type": "step"}), ("assemblies", {"type": "assy"})])
def test_the_schema_refuses_a_connection_property_on_a_shape(kind, declaration, name, value):
    """A part is not a joint, so it has no effort limit, no damping, no spring.

    The shape's vocabulary is the body half of 'physics'. Stating the other half
    on a shape is a mistake about where the property lives rather than metadata
    to carry, and the error names the property so it can be moved.
    """
    config = {kind: {"thing": dict(declaration, properties={"physics": {name: value}})}}
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate(config)
    assert any(
        error.json_path == "$.%s.thing.properties.physics" % kind and name in error.message for error in _errors(config)
    )


def test_the_schema_still_takes_a_connection_property_on_an_interface():
    """Only the shape's vocabulary narrowed - the connection's is untouched."""
    _validate({"interfaces": {"hinge": {"physics": dict(CONNECTION_ONLY_PHYSICS)}}})
    _validate({"interfaces": {"hinge": {"physics": {"damping": 0.5, "friction": 0.4}}}})


def test_declaring_properties_does_not_move_the_cache_key():
    """They say nothing about the geometry, so they must not rehash it.

    A part that gains a material has not become a different shape, and a stale
    entry is not the failure to prefer over a redundant one here: what is cached
    is geometry, and nothing about the geometry changed.
    """
    assert _Part("bolt").hash.get() == _Part("bolt", STEEL).hash.get()


# Onto the envelope
# -----------------


def test_the_metadata_a_shape_is_stamped_with_carries_its_properties():
    assert _Part("bolt", STEEL).get_cache_metadata() == {
        "name": "pkg:bolt",
        "label": "bolt",
        "properties": STEEL,
    }
    # One namespaced key or none: a shape that reports nothing adds nothing.
    assert set(_Part("bolt").get_cache_metadata()) == {"name", "label"}
    assert set(_Part("bolt", {}).get_cache_metadata()) == {"name", "label"}


def test_an_assembly_is_stamped_the_same_way():
    assert _Assembly("rig", BRASS).get_cache_metadata() == {
        "name": "pkg:rig",
        "label": "rig",
        "properties": BRASS,
    }


def test_properties_survive_the_envelope_codec_at_every_level():
    """The wire form is JSON, and a nested dict of them comes back identical."""
    tree = {
        "name": "pkg:rig",
        "label": "rig",
        "properties": BRASS,
        "assembly": [{"name": "pkg:leaf", "label": "leaf", "properties": STEEL, "brep": BREP}],
    }

    text = shape_envelope.dumps(tree)
    # Really JSON, and the properties are in it as they were written.
    assert json.loads(text)["assembly"][0]["properties"] == STEEL

    assert shape_envelope.loads(text) == tree


# Through the cache
# -----------------


def test_the_cache_stores_no_properties_of_its_own_but_keeps_a_child_s(tmp_path):
    """The outer layer is stripped; everything nested inside the payload is not.

    A child's properties describe the tree, which is what the entry is about. The
    assembly's own describe the assembly, which is what the reader supplies.
    """
    cache = _cache(tmp_path)
    cache_hash = _hash()
    child = {"name": "pkg:leaf", "label": "leaf", "properties": STEEL, "brep": BREP}
    tree = {"name": "pkg:first", "label": "first", "properties": BRASS, "assembly": [child]}
    asyncio.run(cache.write_async(cache_hash, {"assembly": tree}))

    stored = json.loads((tmp_path / "cache" / "shapes" / ("%s.assembly" % cache_hash.get())).read_bytes())
    assert stored == {"assembly": [shape_envelope.encode(child)]}
    assert "brass" not in json.dumps(stored)

    metadata = {"name": "pkg:second", "label": "second", "properties": STEEL}
    read, _ = asyncio.run(cache.read_async(cache_hash, ["assembly"], metadata))

    # The root wears the reader's own properties; the child kept its own.
    assert read["assembly"] == dict(metadata, assembly=[child])


def test_shapes_that_share_an_entry_each_get_their_own_properties(tmp_path):
    """The regression the geometry-keyed cache used to cause, for properties.

    Two parts built from the same file share one cache entry. The properties are
    not in the entry - they are stamped on from the configuration of whichever
    part is asking - so the second part cannot inherit the first one's material.
    """
    ctx = _Ctx(tmp_path)
    first = asyncio.run(_Part("first", STEEL).get_wrapped(ctx))
    second = asyncio.run(_Part("second", BRASS).get_wrapped(ctx))
    plain = asyncio.run(_Part("plain").get_wrapped(ctx))

    assert first["properties"] == STEEL
    assert second["properties"] == BRASS
    assert "properties" not in plain


def test_an_assembly_read_back_keeps_its_own_properties_and_its_children_s(tmp_path):
    ctx = _Ctx(tmp_path)
    asyncio.run(_Assembly("first", BRASS, child_properties=STEEL).get_wrapped(ctx))
    second = asyncio.run(_Assembly("second", STEEL, child_properties=STEEL).get_wrapped(ctx))

    assert second["properties"] == STEEL
    # The children came from the cache, and they are what the entry is about.
    assert [child["properties"] for child in second["assembly"]] == [STEEL]


def test_composition_carries_a_child_s_properties_into_the_parent(tmp_path):
    """'Assembly._place()' copies the child's envelope, so they propagate."""
    ctx = _Ctx(tmp_path)
    tree = asyncio.run(_Assembly("rig", child_properties=BRASS).get_wrapped(ctx))

    assert "properties" not in tree
    assert tree["assembly"][0]["properties"] == BRASS


# And into the exporter
# ---------------------


def test_the_index_is_built_from_the_raw_request_by_name():
    """What an implementation that declared 'properties: true' is handed.

    Keyed by the very name each envelope carries, because it is read off that
    envelope - the two cannot disagree the way a separately collected index and
    a separately stamped name could.
    """
    request = {
        "wrapped": {
            "name": "pkg:rig",
            "label": "rig",
            "properties": BRASS,
            "assembly": [
                {"name": "pkg:leaf", "label": "leaf", "properties": STEEL, "brep": "AAAA"},
                # Nested one level deeper, and reporting nothing of its own.
                {
                    "name": "pkg:sub",
                    "label": "sub",
                    "assembly": [{"name": "pkg:deep", "label": "deep", "properties": STEEL, "brep": "AAAA"}],
                },
            ],
        },
        "shape_name": "rig",
        "properties": True,
    }

    assert wrapper_export.properties_index(request) == {
        "pkg:rig": BRASS,
        "pkg:leaf": STEEL,
        "pkg:deep": STEEL,
    }


def test_the_index_is_empty_when_nothing_reports_anything():
    request = {"wrapped": {"name": "pkg:bolt", "label": "bolt", "brep": "AAAA"}, "properties": True}

    assert wrapper_export.properties_index(request) == {}


def test_a_shape_with_no_name_cannot_be_indexed_but_does_not_stop_the_walk():
    request = {
        "wrapped": {
            "name": None,
            "properties": STEEL,
            "assembly": [{"name": "pkg:leaf", "properties": BRASS, "brep": "AAAA"}],
        }
    }

    assert wrapper_export.properties_index(request) == {"pkg:leaf": BRASS}
