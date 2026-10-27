#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What showing a tree again costs: a lookup per shape, and a sandbox for what is new.

The tessellation the IDE draws is cached a shape at a time, keyed on the digest of
the shape's exact geometry and the deflection (see 'shape_gltf.convert_async'), and
the tree is put back together in the core around the glTF of each shape. Three
things follow, and each is pinned here because nothing else would notice it going:

  * a hit is a lookup and nothing more - the tree is never serialized, and no
    sandbox is asked for;
  * an edit of one part sends that part, and only that part, to a sandbox;
  * a tree whose size changes by a hair keeps its deflection, so the shapes in it
    stay hits.

No sandbox and no kernel: the runtime is a stub that answers the wrapper's protocol
and records what it was handed. The payloads are not BREP; nothing here opens one.
"""

import asyncio
import types

import pytest

from partcad import cache_artifacts, runtime, shape_envelope, shape_gltf
from partcad.cache import Cache


def _cache(tmp_path) -> Cache:
    """A files-only cache of its own, so no test reads what another one wrote."""
    config = types.SimpleNamespace(
        cache=True,
        internal_state_dir=str(tmp_path / "state"),
        cache_min_entry_size=100,
        cache_max_entry_size=10 * 1024 * 1024,
    )
    return Cache("artifacts", config)


class _Sandbox:
    """A runtime that answers as 'wrapper_gltf.process' does, and keeps what it was handed.

    A payload starting with b"empty" has nothing to draw, one starting with b"broken"
    will not tessellate, and every other one tessellates to text naming the payload
    and the run - so a test can tell which run produced which entry.
    """

    def __init__(self, fail=None, as_bytes=False):
        self.runs = []
        self.fail = fail
        self.as_bytes = as_bytes

    async def ensure_async(self, *_args, **_kwargs):
        return None

    async def run_async(self, command, request_serialized, **_kwargs):
        request = shape_envelope.deserialize(runtime.stdin_bytes(request_serialized))
        self.runs.append(request)
        if self.fail:
            return 0, shape_envelope.serialize({"success": False, "exception": self.fail}), ""
        geometry, empty, failed = {}, {}, {}
        for shape in request["shapes"]:
            payload = shape[shape_envelope.KEY_BREP]
            if payload.startswith(b"empty"):
                empty[shape["digest"]] = "there are no faces or edges to draw"
            elif payload.startswith(b"broken"):
                failed[shape["digest"]] = "the mesher gave up"
            else:
                text = "glTF of %s, run %d" % (payload.decode(), len(self.runs))
                geometry[shape["digest"]] = text.encode() if self.as_bytes else text
        answer = {
            "success": True,
            "geometry": geometry,
            "empty": empty,
            "failed": failed,
            "tolerance": request["tolerance"],
            "angularTolerance": request["angularTolerance"],
            "mergedFaces": True,
        }
        return 0, shape_envelope.serialize(answer), ""

    def handed(self, run=-1):
        """The payloads one run was handed, in the order it was handed them."""
        return [shape[shape_envelope.KEY_BREP] for shape in self.runs[run]["shapes"]]


def _no_runtime(*_args, **_kwargs):
    raise AssertionError("a sandbox was asked for, for a tree whose every shape is cached")


def _context(tmp_path, sandbox):
    return types.SimpleNamespace(cache_artifacts=_cache(tmp_path), get_python_runtime=lambda **_kwargs: sandbox)


def _part(payload, label, x=0.0, size=10.0):
    """A placed node of 'payload', which records a box 'size' across where it sits."""
    return {
        "name": "//pkg:%s" % label,
        "label": label,
        shape_envelope.KEY_BREP: payload,
        shape_envelope.KEY_LOCATION: [[x, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0],
        shape_envelope.KEY_METADATA: {
            shape_envelope.METADATA_MEASUREMENTS: {shape_envelope.METADATA_BBOX: [0, 0, 0, size, size, size]}
        },
    }


def _assembly(*children, name="//pkg:assembly"):
    return {"name": name, "label": None, shape_envelope.KEY_ASSEMBLY: list(children)}


def _convert(ctx, tree, **kwargs):
    return asyncio.run(shape_gltf.convert_async(ctx, tree, **kwargs))


def _drawn(converted):
    """Each node's label and the glTF it is drawn with, in tree order."""
    geometry = converted[shape_envelope.KEY_GEOMETRY]
    return [
        (child["label"], geometry.get(child.get(shape_envelope.KEY_GLTF_REF)))
        for child in converted[shape_envelope.KEY_ASSEMBLY]
    ]


BOLT, NUT, WASHER = b"bolt", b"nut", b"washer"


def test_a_shape_placed_many_times_is_handed_over_once(tmp_path):
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(*[_part(BOLT, "bolt-%d" % index, x=20.0 * index) for index in range(100)], _part(NUT, "nut"))

    converted = _convert(ctx, tree)

    assert len(sandbox.runs) == 1
    assert sandbox.handed() == [BOLT, NUT]
    assert len(converted[shape_envelope.KEY_GEOMETRY]) == 2
    refs = {child[shape_envelope.KEY_GLTF_REF] for child in converted[shape_envelope.KEY_ASSEMBLY]}
    assert refs == set(converted[shape_envelope.KEY_GEOMETRY])


def test_a_hit_serializes_nothing_and_asks_for_no_sandbox(tmp_path, monkeypatch):
    """The whole point: showing an unchanged tree again is a lookup per distinct shape.

    Before, the key was a digest of the whole request - every payload base64-encoded
    and the tree written out as sorted JSON - computed before the cache was even
    asked, which was seconds of the daemon's time for a large assembly on every show.
    """
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(*[_part(BOLT if index % 2 else NUT, "part-%d" % index, x=20.0 * index) for index in range(50)])
    first = _convert(ctx, tree)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("serialized on a hit")

    monkeypatch.setattr(shape_envelope, "serialize", forbidden)
    monkeypatch.setattr(shape_envelope, "dumps", forbidden)
    monkeypatch.setattr(shape_envelope, "encode", forbidden)
    monkeypatch.setattr(cache_artifacts, "request_key", forbidden)
    monkeypatch.setattr(cache_artifacts, "content_key", forbidden)
    ctx.get_python_runtime = _no_runtime

    second = _convert(ctx, tree)

    assert len(sandbox.runs) == 1
    assert second == first


def test_an_edited_part_is_the_only_one_tessellated_again(tmp_path):
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    _convert(ctx, _assembly(_part(BOLT, "bolt"), _part(NUT, "nut", x=20.0), _part(WASHER, "washer", x=40.0)))

    edited = _convert(
        ctx, _assembly(_part(BOLT, "bolt"), _part(b"nut, edited", "nut", x=20.0), _part(WASHER, "washer", x=40.0))
    )

    assert len(sandbox.runs) == 2
    # The second sandbox was handed the one shape it had not seen, and nothing else.
    assert sandbox.handed() == [b"nut, edited"]
    assert _drawn(edited) == [
        ("bolt", "glTF of bolt, run 1"),
        ("nut", "glTF of nut, edited, run 2"),
        ("washer", "glTF of washer, run 1"),
    ]


def test_cached_and_new_shapes_make_one_tree(tmp_path):
    """And the new ones are remembered too: a third show is a hit throughout."""
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    _convert(ctx, _assembly(_part(BOLT, "bolt")))

    # Where the bolt already was, so that the tree is the size it was and the
    # bolt's entry is at the deflection it is asked for again.
    tree = _assembly(_part(BOLT, "bolt"), _part(NUT, "nut", size=5.0), _part(BOLT, "bolt-2", size=5.0))
    mixed = _convert(ctx, tree)
    assert sandbox.handed() == [NUT]
    assert _drawn(mixed) == [
        ("bolt", "glTF of bolt, run 1"),
        ("nut", "glTF of nut, run 2"),
        ("bolt-2", "glTF of bolt, run 1"),
    ]

    ctx.get_python_runtime = _no_runtime
    assert _convert(ctx, tree) == mixed


def test_the_tree_is_put_back_together_as_it_came(tmp_path):
    """Names, placements, metadata and ports stay in the tree; only the geometry is swapped.

    And the answer is a copy: the BREP tree is what a shape keeps in memory, so a
    reader of the glTF form changing what it was given must not reach it.
    """
    ctx = _context(tmp_path, _Sandbox())
    part = _part(BOLT, "bolt", x=12.5)
    part[shape_envelope.KEY_PORTS] = {"top": {"location": [[0, 0, 10], [0, 0, 1], 0], "sketch": "//pkg:m3"}}
    part[shape_envelope.KEY_PROPERTIES] = {"color": (0.5, 0.5, 0.5)}
    tree = _assembly(part)
    tree[shape_envelope.KEY_SKETCHES] = {"//pkg:m3": {"name": "//pkg:m3", shape_envelope.KEY_BREP: b"circle"}}

    converted = _convert(ctx, tree)

    (node,) = converted[shape_envelope.KEY_ASSEMBLY]
    assert shape_envelope.KEY_BREP not in node
    assert node["name"] == "//pkg:bolt" and node["label"] == "bolt"
    assert node[shape_envelope.KEY_LOCATION] == [[12.5, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    assert node[shape_envelope.KEY_PORTS] == part[shape_envelope.KEY_PORTS]
    assert node[shape_envelope.KEY_METADATA] == part[shape_envelope.KEY_METADATA]
    # As JSON would have it, which is what the tree used to come back through.
    assert node[shape_envelope.KEY_PROPERTIES]["color"] == [0.5, 0.5, 0.5]
    # The sketches a port is drawn with are geometry like any other.
    sketch = converted[shape_envelope.KEY_SKETCHES]["//pkg:m3"]
    assert shape_envelope.KEY_BREP not in sketch
    assert converted[shape_envelope.KEY_GEOMETRY][sketch[shape_envelope.KEY_GLTF_REF]] == "glTF of circle, run 1"

    node[shape_envelope.KEY_METADATA]["changed"] = True
    node[shape_envelope.KEY_LOCATION][0][0] = 99.0
    assert "changed" not in part[shape_envelope.KEY_METADATA]
    assert part[shape_envelope.KEY_LOCATION][0][0] == 12.5
    assert part[shape_envelope.KEY_BREP] == BOLT


def test_a_tree_a_hair_larger_keeps_its_tolerance_and_its_cache(tmp_path):
    """A washer added at the edge moves the diagonal, and moves nothing else.

    Without the rounding, the deflection would follow the diagonal by a hair and
    the key of every shape in the tree with it: one washer, a whole assembly
    tessellated again.
    """
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    _convert(ctx, _assembly(_part(BOLT, "bolt"), _part(NUT, "nut", x=990.0)))
    grown = _assembly(_part(BOLT, "bolt"), _part(NUT, "nut", x=990.0), _part(WASHER, "washer", x=1000.0))
    assert shape_gltf.size_of(grown) != shape_gltf.size_of(_assembly(_part(BOLT, "bolt"), _part(NUT, "nut", x=990.0)))

    _convert(ctx, grown)

    assert sandbox.handed() == [WASHER]
    assert sandbox.runs[0]["tolerance"] == sandbox.runs[1]["tolerance"]


def test_another_tolerance_is_another_tessellation(tmp_path):
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))

    _convert(ctx, tree)
    _convert(ctx, tree, tolerance=0.01)
    _convert(ctx, tree, tolerance=0.01, angular_tolerance=0.1)
    _convert(ctx, tree, tolerance=0.01, angular_tolerance=0.1)

    assert len(sandbox.runs) == 3
    assert [run["angularTolerance"] for run in sandbox.runs] == [shape_gltf.DEFAULT_ANGULAR_TOLERANCE, 0.4, 0.1]


def test_another_wrapper_is_another_tessellation(tmp_path, monkeypatch):
    """The wrapper's code is in the key, so two encodings of a payload never mix.

    What a payload is - how the glTF is compressed, how it is written down - is the
    wrapper's business and opaque here, so the only thing that keeps an entry
    written by one release from being read as though another had written it is
    that the two are under different keys.
    """
    from partcad import source_key

    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))
    _convert(ctx, tree)

    monkeypatch.setattr(source_key, "wrappers_key", lambda: "the wrappers of another release")
    _convert(ctx, tree)

    assert len(sandbox.runs) == 2


def test_a_payload_comes_back_as_it_went_in(tmp_path):
    """Text as text and bytes as bytes, from a run and from the cache alike."""
    for as_bytes in (False, True):
        sandbox = _Sandbox(as_bytes=as_bytes)
        ctx = _context(tmp_path / str(as_bytes), sandbox)
        tree = _assembly(_part(BOLT, "bolt"))

        ran = _convert(ctx, tree)
        ctx.get_python_runtime = _no_runtime
        cached = _convert(ctx, tree)

        expected = b"glTF of bolt, run 1" if as_bytes else "glTF of bolt, run 1"
        assert _drawn(ran) == _drawn(cached) == [("bolt", expected)]
        assert type(_drawn(cached)[0][1]) is type(expected)


def test_what_is_not_cacheable_is_neither_read_nor_remembered(tmp_path):
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))

    _convert(ctx, tree)
    _convert(ctx, tree, cacheable=False)
    _convert(ctx, tree, cacheable=False)

    assert len(sandbox.runs) == 3


def test_without_a_cache_everything_is_tessellated(tmp_path):
    sandbox = _Sandbox()
    ctx = types.SimpleNamespace(cache_artifacts=None, get_python_runtime=lambda **_kwargs: sandbox)
    tree = _assembly(_part(BOLT, "bolt"), _part(BOLT, "again"))

    assert _drawn(_convert(ctx, tree)) == [("bolt", "glTF of bolt, run 1"), ("again", "glTF of bolt, run 1")]
    _convert(ctx, tree)
    assert len(sandbox.runs) == 2


def test_a_tree_with_no_geometry_asks_for_no_sandbox(tmp_path):
    """An interface whose ports carry no boundary has nothing to tessellate."""
    ctx = types.SimpleNamespace(cache_artifacts=_cache(tmp_path), get_python_runtime=_no_runtime)
    converted = _convert(ctx, _assembly(name="//pkg:empty"))
    assert converted == {"name": "//pkg:empty", "label": None, shape_envelope.KEY_ASSEMBLY: [], "geometry": {}}


def test_a_failed_sandbox_raises_and_remembers_nothing(tmp_path):
    sandbox = _Sandbox(fail="no OCP")
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))

    for _ in range(2):
        with pytest.raises(Exception, match="no OCP"):
            _convert(ctx, tree)
    assert len(sandbox.runs) == 2

    sandbox.fail = None
    assert _drawn(_convert(ctx, tree)) == [("bolt", "glTF of bolt, run 3")]


def test_a_crashed_sandbox_raises(tmp_path):
    class Crashing(_Sandbox):
        async def run_async(self, command, request_serialized, **_kwargs):
            self.runs.append(None)
            return -11, "", ""

    sandbox = Crashing()
    ctx = _context(tmp_path, sandbox)
    with pytest.raises(Exception, match="Failed to tessellate"):
        _convert(ctx, _assembly(_part(BOLT, "bolt")))


def test_a_shape_that_will_not_tessellate_is_tried_again_alone(tmp_path, caplog):
    """Only an answer is remembered, and why a shape failed may be the sandbox's doing.

    The rest of the tree is remembered all the same, so trying the one shape again
    costs a sandbox handed that shape and nothing else.
    """
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"), *[_part(b"broken", "bad-%d" % index, x=5.0) for index in range(3)])

    with caplog.at_level("WARNING"):
        first = _convert(ctx, tree)
    # Reported once for the shape, against the first node made of it, not once per node.
    assert caplog.text.count("Nothing to draw for bad-0: the mesher gave up") == 1
    assert "bad-1" not in caplog.text
    assert _drawn(first) == [("bolt", "glTF of bolt, run 1"), ("bad-0", None), ("bad-1", None), ("bad-2", None)]
    assert all(shape_envelope.KEY_GLTF_REF not in child for child in first[shape_envelope.KEY_ASSEMBLY][1:])

    _convert(ctx, tree)
    assert sandbox.handed() == [b"broken"]


def test_a_shape_with_nothing_to_draw_is_an_answer(tmp_path, caplog):
    """No face and no edge is a fact about the geometry, so it is remembered, reason and all."""
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"), _part(b"empty compound", "point", x=5.0))
    _convert(ctx, tree)

    ctx.get_python_runtime = _no_runtime
    with caplog.at_level("WARNING"):
        again = _convert(ctx, tree)

    assert "Nothing to draw for point: there are no faces or edges to draw" in caplog.text
    assert _drawn(again) == [("bolt", "glTF of bolt, run 1"), ("point", None)]


def test_a_lone_shape_with_nothing_to_draw_leaves_no_tree(tmp_path):
    """A part, rather than a node of an assembly: there is nothing left to show at all."""
    ctx = _context(tmp_path, _Sandbox())
    with pytest.raises(Exception, match="no shape tree"):
        _convert(ctx, _part(b"broken", "bad"))


def test_a_shape_the_sandbox_said_nothing_about_is_not_remembered(tmp_path):
    class Forgetful(_Sandbox):
        async def run_async(self, command, request_serialized, **kwargs):
            request = shape_envelope.deserialize(runtime.stdin_bytes(request_serialized))
            self.runs.append(request)
            return 0, shape_envelope.serialize({"success": True, "geometry": {}}), ""

    sandbox = Forgetful()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))

    assert _drawn(_convert(ctx, tree)) == [("bolt", None)]
    _convert(ctx, tree)
    assert len(sandbox.runs) == 2


def test_an_entry_that_cannot_be_read_is_a_miss(tmp_path):
    """Read from tiers other machines write to, so anything unrecognised is tessellated again."""
    sandbox = _Sandbox()
    ctx = _context(tmp_path, sandbox)
    tree = _assembly(_part(BOLT, "bolt"))
    _convert(ctx, tree)

    directory = tmp_path / "state" / "cache" / "artifacts"
    (entry,) = [path for path in directory.iterdir() if ".artifact-" in path.name]
    entry.write_bytes(b"?something else")

    assert _drawn(_convert(ctx, tree)) == [("bolt", "glTF of bolt, run 2")]


def test_each_shape_is_its_own_entry_stored_as_it_came(tmp_path):
    """Not recompressed: the payload is already deflated, so an entry is its bytes and a tag."""
    ctx = _context(tmp_path, _Sandbox())
    _convert(ctx, _assembly(_part(BOLT, "bolt"), _part(NUT, "nut")))

    directory = tmp_path / "state" / "cache" / "artifacts"
    entries = sorted(path.read_bytes() for path in directory.iterdir() if ".artifact-" in path.name)
    assert entries == [b"tglTF of bolt, run 1", b"tglTF of nut, run 1"]
