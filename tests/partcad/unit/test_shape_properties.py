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
from partcad.cache_shape import ShapeCache, properties_key
from partcad.lint.all import get_partcad_schema
from partcad.shape import Shape

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_export  # noqa: E402

# Not a real BREP, but it starts the way an uncompressed payload does, which is
# all the cache uses to tell a raw payload from a JSON one.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"

STEEL = {"material": "steel", "color": "#8899AA"}
BRASS = {"material": "brass", "physics": {"mass": 0.25}}


def _cache(tmp_path, **overrides):
    return ShapeCache(user_config=CacheUserConfig(tmp_path, **overrides))


def _hash():
    cache_hash = CacheHash("geometry", cache=True)
    # Every shape below builds the same geometry, and so shares one entry.
    cache_hash.add_string("identical-geometry")
    return cache_hash


def _entry(tmp_path, cache_hash, key):
    """The file one cache entry is stored in, whether or not it is there."""
    return tmp_path / "cache" / "shapes" / ("%s.%s" % (cache_hash.get(), key))


class _Ctx:
    def __init__(self, tmp_path, **overrides):
        self.cache_shapes = _cache(tmp_path, **overrides)


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

    stored = json.loads(_entry(tmp_path, cache_hash, "assembly").read_bytes())
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


# In an entry of their own
# ------------------------


def test_instantiating_a_shape_fills_the_geometry_entry_and_the_properties_one(tmp_path):
    """Both, and by the one path that actually built the shape.

    The key is the geometry's with a suffix, so the two sit side by side in
    whatever tier took them and neither can be mistaken for the other.
    """
    ctx = _Ctx(tmp_path)
    part = _Part("bolt", STEEL)
    asyncio.run(part.get_wrapped(ctx))

    assert properties_key("part") == "part-props"
    assert _entry(tmp_path, part.hash, "part").read_bytes() == BREP
    assert json.loads(_entry(tmp_path, part.hash, properties_key("part")).read_bytes()) == STEEL


def test_the_properties_are_materialized_without_the_geometry(tmp_path):
    """Asking what a shape is made of does not pull its BREP out of the cache."""
    ctx = _Ctx(tmp_path)
    part = _Part("bolt", STEEL)
    asyncio.run(part.get_wrapped(ctx))
    _entry(tmp_path, part.hash, "part").unlink()

    # A later run of the same part, with no geometry left to read.
    assert asyncio.run(_Part("bolt", STEEL).get_cached_properties_async(ctx)) == STEEL


def test_the_geometry_is_materialized_without_the_properties(tmp_path):
    """A cache from before the properties had an entry is not a miss for the geometry.

    The two go stale on different occasions and are read on different ones, so
    the absence of either has to leave the other alone.
    """
    ctx = _Ctx(tmp_path)
    first = _Part("first", STEEL)
    asyncio.run(first.get_wrapped(ctx))
    _entry(tmp_path, first.hash, properties_key("part")).unlink()

    second = asyncio.run(_Part("second", BRASS).get_wrapped(ctx))

    assert second == {"name": "pkg:second", "label": "second", "properties": BRASS, "brep": BREP}
    assert asyncio.run(_Part("second", BRASS).get_cached_properties_async(ctx)) is None


def test_a_shape_that_reports_nothing_leaves_no_properties_entry(tmp_path):
    """One entry or none, the way one stamped key or none is."""
    ctx = _Ctx(tmp_path)
    plain = _Part("plain")
    asyncio.run(plain.get_wrapped(ctx))

    assert not _entry(tmp_path, plain.hash, properties_key("part")).exists()
    assert asyncio.run(_Part("plain").get_cached_properties_async(ctx)) is None


def test_the_properties_entry_is_not_filtered_out_by_the_geometry_size_window(tmp_path):
    """It is named after a geometry key without being geometry.

    A tier drops entries below its minimum to keep trivial geometry out of the
    cache - 100 bytes for the files tier by default. A handful of declared
    values is always under that, so applying the window to them would leave the
    entry never written at all.
    """
    ctx = _Ctx(tmp_path, cache_min_entry_size=100)
    part = _Part("bolt", STEEL)
    asyncio.run(part.get_wrapped(ctx))

    # The window really is on: the geometry below it was dropped.
    assert len(BREP) < 100 and not _entry(tmp_path, part.hash, "part").exists()
    assert json.loads(_entry(tmp_path, part.hash, properties_key("part")).read_bytes()) == STEEL


def test_an_assembly_s_own_go_to_its_entry_and_its_children_s_stay_in_the_tree(tmp_path):
    """The split, end to end: the root's are the asking object's, a child's are the tree's."""
    ctx = _Ctx(tmp_path)
    rig = _Assembly("rig", BRASS, child_properties=STEEL)
    asyncio.run(rig.get_wrapped(ctx))

    stored = json.loads(_entry(tmp_path, rig.hash, "assembly").read_bytes())
    assert [child["properties"] for child in stored["assembly"]] == [STEEL]
    assert "brass" not in json.dumps(stored)
    assert json.loads(_entry(tmp_path, rig.hash, properties_key("assembly")).read_bytes()) == BRASS


def test_a_properties_entry_is_carried_as_the_plain_dict_it_is(tmp_path):
    """It has no payload, so there is no outer layer to strip or to stamp back on."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    key = properties_key("part")
    asyncio.run(cache.write_async(cache_hash, {key: BRASS}))

    assert json.loads(_entry(tmp_path, cache_hash, key).read_bytes()) == BRASS

    read, _ = asyncio.run(cache.read_async(cache_hash, [key], {"name": "pkg:x", "label": "x"}))

    assert read[key] == BRASS


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


# What a shape inherits from its material
# ---------------------------------------


def test_a_material_fills_in_what_the_shape_did_not_state():
    """The whole of how 'mu' reaches an exporter, and why none of them changed.

    The core resolves each shape's material and sends what it says beside the
    shapes; the index folds it in underneath the shape's own physics. An
    exporter goes on reading 'physics' and never learns materials exist - which
    is what makes URDF, SDFormat and MJCF agree about friction for free.
    """
    request = {
        "wrapped": {
            "name": "pkg:leaf",
            "label": "leaf",
            "properties": {"material": ":ptfe"},
            "brep": "AAAA",
        },
        "properties": True,
        "__materials__": {"pkg:leaf": {"friction": 0.04}},
    }

    assert wrapper_export.properties_index(request) == {
        "pkg:leaf": {"material": ":ptfe", "physics": {"friction": 0.04}},
    }


def test_what_the_shape_states_itself_wins_over_its_material():
    """A part that has been measured beats the substance it is made of."""
    request = {
        "wrapped": {
            "name": "pkg:leaf",
            "properties": {"material": ":ptfe", "physics": {"friction": 0.9, "mass": 2.0}},
            "brep": "AAAA",
        },
        "properties": True,
        "__materials__": {"pkg:leaf": {"friction": 0.04}},
    }

    index = wrapper_export.properties_index(request)
    assert index["pkg:leaf"]["physics"] == {"friction": 0.9, "mass": 2.0}


def test_the_table_is_keyed_by_shape_so_a_reference_can_be_relative():
    """Two packages may each catalogue an 'aluminium' of their own.

    ':aluminium' means "in my own package", so which material it is is a fact
    about the shape that wrote it rather than about the string - which is why
    the core resolves it and keys what it found by shape.
    """
    request = {
        "wrapped": {
            "name": "pkg:rig",
            "assembly": [
                {"name": "a:part", "properties": {"material": ":aluminium"}, "brep": "AAAA"},
                {"name": "b:part", "properties": {"material": ":aluminium"}, "brep": "BBBB"},
            ],
        },
        "properties": True,
        "__materials__": {"a:part": {"friction": 1.05}, "b:part": {"friction": 0.2}},
    }

    index = wrapper_export.properties_index(request)
    assert index["a:part"]["physics"] == {"friction": 1.05}
    assert index["b:part"]["physics"] == {"friction": 0.2}


def test_a_shape_with_no_material_is_left_exactly_as_it_was():
    request = {
        "wrapped": {"name": "pkg:leaf", "properties": STEEL, "brep": "AAAA"},
        "properties": True,
        "__materials__": {"pkg:other": {"friction": 0.04}},
    }

    assert wrapper_export.properties_index(request) == {"pkg:leaf": STEEL}


def test_the_material_table_is_not_walked_for_shapes():
    """It is keyed by name and holds no envelopes; walking it would find none."""
    request = {
        "wrapped": {"name": "pkg:leaf", "properties": STEEL, "brep": "AAAA"},
        "properties": True,
        "__materials__": {"pkg:leaf": {"friction": 0.04}, "brep": "not a shape"},
    }

    index = wrapper_export.properties_index(request)
    assert set(index) == {"pkg:leaf"}


def test_the_material_parameter_is_the_material_too(tmp_path):
    """Two places name it, and they mean the same thing.

    ':ref:`materials`' in the configuration guide documents the parameter form,
    and 'properties:' documents the other; a part that wrote either is made of
    what it said, so both reach an exporter - and a simulation - as one
    property.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cube.stl").write_text("", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //p\n"
        "parts:\n"
        "  as_parameter:\n"
        "    type: stl\n    path: cube.stl\n"
        "    parameters:\n      material:\n        type: string\n        default: '//cat:pla'\n"
        "  as_property:\n"
        "    type: stl\n    path: cube.stl\n"
        "    properties:\n      material: '//cat:abs'\n"
        "  both:\n"
        "    type: stl\n    path: cube.stl\n"
        "    parameters:\n      material:\n        type: string\n        default: '//cat:pla'\n"
        "    properties:\n      material: '//cat:abs'\n",
        encoding="utf-8",
    )
    project = pc.Context(str(root)).get_project("//")

    assert project.get_part("as_parameter")._shape_properties() == {"material": "//cat:pla"}
    assert project.get_part("as_property")._shape_properties() == {"material": "//cat:abs"}
    # What the shape says about itself wins, the way it does everywhere else.
    assert project.get_part("both")._shape_properties() == {"material": "//cat:abs"}
