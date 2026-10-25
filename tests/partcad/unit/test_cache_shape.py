#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The shape cache stores geometry, and nothing that identifies the shape."""

import asyncio
import base64
import json

from cache_config import CacheUserConfig

from partcad import cache_shape, shape_envelope
from partcad.assembly import Assembly
from partcad.cache_hash import CacheHash
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

# Not a real BREP, and not compressed either, but it starts the way an
# uncompressed payload does - which is all the cache uses to tell a raw payload
# from a JSON one.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"


class _Ctx:
    """The little of a context that getting a shape needs."""

    def __init__(self, tmp_path):
        self.cache_shapes = _cache(tmp_path)


def _cache(tmp_path):
    return ShapeCache(user_config=CacheUserConfig(tmp_path))


def _hash(name="geometry"):
    cache_hash = CacheHash(name, cache=True)
    # Every shape below is hashed on its geometry alone, which is what makes
    # them share one entry.
    cache_hash.add_string("identical-geometry")
    return cache_hash


def _shape(name, label):
    return {"name": name, "label": label, "brep": BREP}


def _entry(tmp_path, cache_hash, key):
    return (tmp_path / "cache" / "shapes" / ("%s.%s" % (cache_hash.get(), key))).read_bytes()


def test_shapes_sharing_an_entry_keep_their_own_name_and_label(tmp_path):
    """Regression: the name of whichever shape was cached first leaked onto the rest.

    The cache is keyed on what produces the geometry, so two parts that build
    the same geometry share one entry. The entry used to carry the JSON envelope
    of the first one to reach it - name, label and all - and every later reader
    got that shape's identity back instead of its own.
    """
    cache = _cache(tmp_path)
    asyncio.run(cache.write_async(_hash(), {"part": _shape("pkg:first", "first")}))

    read, _ = asyncio.run(cache.read_async(_hash(), ["part"], {"name": "pkg:second", "label": "second"}))

    assert read["part"] == _shape("pkg:second", "second")


def test_a_lone_shape_is_stored_as_the_brep_bytes_alone(tmp_path):
    """No outer layer on disk at all - not even the JSON that used to carry it."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    asyncio.run(cache.write_async(cache_hash, {"part": _shape("pkg:first", "first")}))

    assert _entry(tmp_path, cache_hash, "part") == BREP


def test_an_assembly_keeps_its_children_but_not_its_own_outer_layer(tmp_path):
    """A child's name/label/placement describe the tree, so they are geometry here.

    Only the outer layer of the assembly itself - which says which assembly this
    is and where it sits - is left out and supplied by the reader.
    """
    cache = _cache(tmp_path)
    cache_hash = _hash()
    child = dict(_shape("pkg:child", "child"), location=[[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0])
    tree = {
        "name": "pkg:first",
        "label": "first",
        "location": [[9.0, 9.0, 9.0], [0.0, 0.0, 1.0], 0.0],
        "assembly": [child],
    }
    asyncio.run(cache.write_async(cache_hash, {"assembly": tree}))

    # A tree is a frame (see 'cache_shape._TREE_MAGIC'): its structure, and each
    # payload once after it, as the bytes it is rather than as base64.
    stored = _entry(tmp_path, cache_hash, "assembly")
    assert stored.startswith(cache_shape._TREE_MAGIC)
    assert BREP in stored
    assert base64.b64encode(BREP) not in stored
    assert cache_shape._deserialize(stored) == {"assembly": [child]}

    metadata = {"name": "pkg:second", "label": "second", "location": [[1.0, 2.0, 3.0], [0.0, 0.0, 1.0], 0.0]}
    read, _ = asyncio.run(cache.read_async(cache_hash, ["assembly"], metadata))

    assert read["assembly"] == dict(metadata, assembly=[child])


def test_components_are_stamped_with_the_reader_own_metadata(tmp_path):
    """The components of a shape are cached as a list, and stripped item by item."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    components = [_shape("pkg:first", "first"), [_shape("pkg:first", "first")]]
    asyncio.run(cache.write_async(cache_hash, {"cmps": components}))

    assert b"pkg:first" not in _entry(tmp_path, cache_hash, "cmps")

    read, _ = asyncio.run(cache.read_async(cache_hash, ["cmps"], {"name": "pkg:second", "label": "second"}))

    assert read["cmps"] == [_shape("pkg:second", "second"), [_shape("pkg:second", "second")]]


def test_a_miss_is_reported_as_a_miss(tmp_path):
    read, in_memory = asyncio.run(_cache(tmp_path).read_async(_hash(), ["part"], {"name": "pkg:a", "label": "a"}))

    assert read == {"part": None}
    assert in_memory == {"part": False}


class _Part(Shape):
    """A part whose factory hands back an envelope, with no sandbox involved."""

    def __init__(self, name):
        super().__init__("pkg", {"name": name})
        self.name = name
        self.kind = "part"
        # Every part below builds the same geometry, and so shares one entry.
        self.hash.add_string("identical-geometry")

    async def get_shape(self, ctx):
        return {"name": None, "label": None, "brep": BREP}


class _Assembly(Assembly):
    def __init__(self, name, location=None):
        config = {"name": name}
        if location is not None:
            config["location"] = location
        super().__init__("pkg", config)
        self.name = name
        self.hash.add_string("identical-geometry")

    def instantiate(self, _assembly):
        child = _Part("leaf")
        child.cacheable = False
        self.add(child, name="leaf")


def test_a_part_read_back_from_a_shared_entry_is_itself(tmp_path):
    """The whole path: one part fills the entry, another reads it and stays itself."""
    ctx = _Ctx(tmp_path)
    first = asyncio.run(_Part("first").get_wrapped(ctx))
    second = asyncio.run(_Part("second").get_wrapped(ctx))

    assert first == _shape("pkg:first", "first")
    assert second == _shape("pkg:second", "second")


def test_an_assembly_read_back_from_a_shared_entry_keeps_its_own_placement(tmp_path):
    """Same children, but the placement of the assembly asking - not of the one cached."""
    ctx = _Ctx(tmp_path)
    location = [[1.0, 2.0, 3.0], [0.0, 0.0, 1.0], 0.0]
    asyncio.run(_Assembly("first").get_wrapped(ctx))
    second = asyncio.run(_Assembly("second", location=location).get_wrapped(ctx))

    assert second["name"] == "pkg:second"
    assert second["label"] == "second"
    assert second["location"] == location
    # The children came from the cache, and they are what the entry is about.
    assert [child["name"] for child in second["assembly"]] == ["pkg:leaf"]


# --------------------------------------------------------------------------- #
# A tree, each distinct payload once                                          #
# --------------------------------------------------------------------------- #


def _castle(placements=50):
    """Many placements of two parts, the way an assembly built in this process holds them."""
    brick, cone = BREP + b"brick" * 200, BREP + b"cone" * 200
    children = [
        dict(_shape("pkg:part", "p%d" % i), brep=brick if i % 5 else cone, location=[[i, 0, 0], [0, 0, 1], 0])
        for i in range(placements)
    ]
    return {"name": "pkg:castle", "label": "castle", "assembly": children}


def test_a_tree_stores_each_distinct_payload_once(tmp_path):
    cache = _cache(tmp_path)
    cache_hash = _hash()
    tree = _castle()
    asyncio.run(cache.write_async(cache_hash, {"assembly": tree}))

    stored = _entry(tmp_path, cache_hash, "assembly")
    legacy = json.dumps(shape_envelope.encode(shape_envelope.strip_metadata(tree))).encode("utf-8")
    assert stored.count(BREP) == 2
    assert len(stored) * 10 < len(legacy)


def test_a_tree_read_back_holds_each_payload_once(tmp_path):
    """Every node that names one payload gets the same bytes object, as a tree built here does."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    asyncio.run(cache.write_async(cache_hash, {"assembly": _castle()}))

    read, _ = asyncio.run(cache.read_async(cache_hash, ["assembly"], {"name": "pkg:castle", "label": "castle"}))

    payloads = [child["brep"] for child in read["assembly"]["assembly"]]
    assert read["assembly"]["assembly"] == _castle()["assembly"]
    assert len({id(payload) for payload in payloads}) == 2


def test_a_tree_keeps_what_was_recorded_about_it(tmp_path):
    tree = dict(_castle(3), metadata={"measurements": {"bbox": [0, 0, 0, 1, 1, 1]}})

    read = cache_shape._deserialize(cache_shape._serialize(tree))

    assert read["metadata"] == {"measurements": {"bbox": [0, 0, 0, 1, 1, 1]}}
    assert read["assembly"] == tree["assembly"]


def test_a_tree_an_earlier_release_wrote_is_still_read(tmp_path):
    """Plain JSON with a payload per node: what every entry was before the frame."""
    tree = shape_envelope.strip_metadata(_castle(3))

    read = cache_shape._deserialize(json.dumps(shape_envelope.encode(tree)).encode("utf-8"))

    assert read == tree


def test_a_tree_cut_short_is_refused_and_so_a_miss(tmp_path):
    stored = cache_shape._serialize(_castle())

    try:
        cache_shape._deserialize(stored[: len(stored) - 10])
    except ValueError:
        pass
    else:
        raise AssertionError("a truncated entry was read")

    cache = _cache(tmp_path)
    cache_hash = _hash()
    asyncio.run(cache.write_data_async(cache_hash, {"assembly": stored[: len(stored) - 10]}))
    read, _ = asyncio.run(cache.read_async(cache_hash, ["assembly"]))
    assert read["assembly"] is None


def test_what_is_not_an_assembly_stays_plain_json(tmp_path):
    """A part's components sit beside its geometry; an earlier release must miss neither or both.

    It reads plain JSON and counts a frame it does not know a miss. Framed, the
    components would be its miss while the geometry beside them was its hit: a
    part handed back without its components.
    """
    components = [_shape("pkg:a", "a"), _shape("pkg:a", "b")]

    stored = cache_shape._serialize(components)

    assert not stored.startswith(cache_shape._TREE_MAGIC)
    assert json.loads(stored)
    assert [item["brep"] for item in cache_shape._deserialize(stored)] == [BREP, BREP]
