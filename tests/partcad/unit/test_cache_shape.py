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


def _header(stored):
    """The length of a tree frame's header, and the header itself."""
    length = int.from_bytes(stored[len(cache_shape._TREE_MAGIC) + 1 : cache_shape._TREE_HEADER], "big")
    compressed = stored[cache_shape._TREE_HEADER : cache_shape._TREE_HEADER + length]
    return length, json.loads(cache_shape._ZstdDecompressor().decompress(compressed))


def _with_sizes(stored, sizes):
    """'stored', a tree frame, with the sizes its header gives its payloads replaced."""
    length, header = _header(stored)
    header["payloads"] = [[digest, size] for (digest, _), size in zip(header["payloads"], sizes)]
    encoded = json.dumps(header).encode("utf-8")
    return b"".join(
        [
            cache_shape._TREE_MAGIC,
            cache_shape._TREE_PLAIN,
            len(encoded).to_bytes(4, "big"),
            encoded,
            stored[cache_shape._TREE_HEADER + length :],
        ]
    )


def test_a_tree_whose_header_gives_an_impossible_size_is_refused():
    """A negative size passed the bounds check and moved every later payload onto the wrong bytes."""
    stored = cache_shape._serialize(_castle())
    sizes = [size for _, size in _header(stored)[1]["payloads"]]
    assert len(sizes) == 2
    # Unchanged, the rewritten frame reads back: what follows is the sizes, not the rewriting.
    assert cache_shape._deserialize(_with_sizes(stored, sizes)) == cache_shape._deserialize(stored)

    for impossible in ([-1, sizes[0] + sizes[1] + 1], [1.5, sizes[1]], [True, sizes[1]]):
        try:
            cache_shape._deserialize(_with_sizes(stored, impossible))
        except ValueError:
            continue
        raise AssertionError("a tree with payload sizes %r was read" % (impossible,))

    # Sizes that stop short of the end leave bytes no payload accounts for.
    try:
        cache_shape._deserialize(_with_sizes(stored, [sizes[0], sizes[1] - 1]))
    except ValueError:
        pass
    else:
        raise AssertionError("a tree with bytes after its last payload was read")


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


# A compound's payload, with something in it to find - and to find missing.
COMPOUND = BREP + b"Compound of three solids\n" * 64


def _piece(child, name="pkg:first", label="first", payload=COMPOUND):
    """A component that is a piece of the compound beside it (shape_envelope.KEY_CHILD)."""
    piece = {"name": name, "label": label, "brep": payload, shape_envelope.KEY_CHILD: child}
    piece[shape_envelope.KEY_METADATA] = {"measurements": {"solids": 1, "volume": 10.0 + child}}
    return piece


def test_components_that_are_pieces_of_the_geometry_beside_them_do_not_repeat_it(tmp_path):
    """The compound is cached once: its components' entry says which pieces of it they are."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    shape = {"name": "pkg:first", "label": "first", "brep": COMPOUND}
    components = [_piece(0), [_piece(1), _piece(2)]]

    asyncio.run(cache.write_async(cache_hash, {"part": shape, "cmps": components}))

    stored = _entry(tmp_path, cache_hash, "cmps")
    assert COMPOUND not in stored
    assert len(stored) < len(COMPOUND)

    metadata = {"name": "pkg:second", "label": "second"}
    read, _ = asyncio.run(cache.read_async(cache_hash, ["part", "cmps"], metadata))

    assert read["cmps"] == [
        _piece(0, "pkg:second", "second"),
        [_piece(1, "pkg:second", "second"), _piece(2, "pkg:second", "second")],
    ]
    # And held once in memory, too: every piece is the geometry's own bytes.
    assert all(piece["brep"] is read["part"]["brep"] for piece in [read["cmps"][0]] + read["cmps"][1])


def test_pieces_read_without_the_geometry_beside_them_are_a_miss(tmp_path):
    cache = _cache(tmp_path)
    cache_hash = _hash()
    asyncio.run(cache.write_async(cache_hash, {"part": {"brep": COMPOUND}, "cmps": [_piece(0)]}))

    read, in_memory = asyncio.run(cache.read_async(cache_hash, ["cmps"], {"name": "pkg:a", "label": "a"}))

    assert read == {"cmps": None}
    assert in_memory == {"cmps": False}


def test_pieces_of_other_geometry_than_the_entry_beside_them_are_a_miss(tmp_path):
    """Written beside one build's compound, read beside another's: not its pieces."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    asyncio.run(cache.write_async(cache_hash, {"part": {"brep": COMPOUND}, "cmps": [_piece(0)]}))
    asyncio.run(cache.write_async(cache_hash, {"part": {"brep": COMPOUND + b"rebuilt\n"}}))

    read, _ = asyncio.run(cache.read_async(cache_hash, ["part", "cmps"], {"name": "pkg:a", "label": "a"}))

    assert read["part"]["brep"] == COMPOUND + b"rebuilt\n"
    assert read["cmps"] is None


def test_a_tier_keeps_pieces_wherever_it_keeps_the_geometry_they_name(tmp_path):
    """A size window must not keep the geometry and drop its components: that hit comes back without them.

    The pieces' entry is a few hundred bytes whatever the compound weighs, so a
    tier that refuses entries that small - every persistent tier does, at 100
    bytes by default - would take the compound and refuse its components.
    """
    cache = ShapeCache(user_config=CacheUserConfig(tmp_path, cache_min_entry_size=len(COMPOUND)))
    cache_hash = _hash()
    components = [_piece(0), _piece(1)]
    assert len(cache_shape._serialize(components, {"part": COMPOUND})) < len(COMPOUND)

    asyncio.run(cache.write_async(cache_hash, {"part": {"brep": COMPOUND}, "cmps": components}))

    read, _ = asyncio.run(cache.read_async(cache_hash, ["part", "cmps"], {"name": "pkg:first", "label": "first"}))
    assert read["part"]["brep"] == COMPOUND
    assert read["cmps"] == components


def test_a_tier_that_refuses_the_geometry_refuses_the_pieces_that_name_it(tmp_path):
    cache = ShapeCache(user_config=CacheUserConfig(tmp_path, cache_max_entry_size=len(COMPOUND) - 1))
    cache_hash = _hash()

    asyncio.run(cache.write_async(cache_hash, {"part": {"brep": COMPOUND}, "cmps": [_piece(0)]}))

    assert not (tmp_path / "cache" / "shapes" / ("%s.cmps" % cache_hash.get())).exists()


def test_pieces_of_geometry_not_beside_them_carry_it_once(tmp_path):
    """A part moved by its 'offset' keeps the components of what it moved, as it always did."""
    cache = _cache(tmp_path)
    cache_hash = _hash()
    moved = {"brep": BREP + b"moved\n"}
    components = [_piece(0), _piece(1), _piece(2)]

    asyncio.run(cache.write_async(cache_hash, {"part": moved, "cmps": components}))

    stored = _entry(tmp_path, cache_hash, "cmps")
    assert stored.count(COMPOUND) == 1
    read, _ = asyncio.run(cache.read_async(cache_hash, ["cmps"], {"name": "pkg:first", "label": "first"}))
    assert read["cmps"] == components


def test_components_that_are_pieces_are_written_where_no_earlier_release_reads(tmp_path):
    """The one framed component entry, and why that is safe: its key is one no earlier release computes.

    'test_what_is_not_an_assembly_stays_plain_json' is the rule; this is its
    exception. The wrappers that make pieces raised their CACHE_VERSION when
    they started to, and a shape's key carries the versions of the wrappers
    that build it - which is what keeps an earlier release from ever being the
    one to read this frame and miss it while hitting the part beside it.
    """
    from partcad import code_version, wrapper

    stored = cache_shape._serialize([_piece(0)], {"part": COMPOUND})

    assert stored.startswith(cache_shape._TREE_MAGIC)
    for name in ("build123d.py", "cadquery.py"):
        assert code_version.declared(wrapper.get(name)) >= 2


def test_the_file_tier_takes_a_tree_of_fifty_megabytes_by_default(monkeypatch, tmp_path):
    """Over 10 MB, the LEGO F1's tree (10.9 MB of distinct geometry) was put together again on every run."""
    # A home with no configuration in it, so that the default is what is read
    # and not whatever the machine running the test configured.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_CACHE_FILES_MAX_ENTRY_SIZE", raising=False)
    from partcad_utils.user_config import UserConfig

    assert UserConfig().cache_max_entry_size == 50 * 1024 * 1024
