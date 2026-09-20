#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What was recorded about a shape when it was built, as 'pc info' reports it.

How big a part is and how much of it there is are the two numbers a reader
wants before any other, and neither can be read off a declaration: a part is a
script, a file or a boolean of two others, so the only way to know its size is
to have built it.

Which is the whole design. The size is measured **as the shape is built**, by
the code that is holding the live geometry, and travels back with it in the
envelope's metadata - beside what the source file stated, and what it stated
about individual elements. One envelope carries the lot, one cache entry stores
the lot, and one cache hit answers the lot.

The measuring itself is OCCT's and is covered by 'test_wrapper_measure'; what
is covered here is the core's half: that nothing is computed on demand, that
the geometry and what is known about it are one entry rather than four, that a
shape which did not build reports nothing rather than an invented nothing, and
which keys the numbers become for 'pc info'.

The core is deliberately unable to tell any of these sections apart from any
other. The sections a file stated are its own vocabulary, and which format
answered is not a question the core asks.
"""

import asyncio

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import cache_shape
from partcad import measure as pc_measure
from partcad import shape_envelope
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

MEASURED = {"bbox": [-1.0, 0.0, 2.0, 9.0, 20.0, 5.0], "volume": 1500.0, "solids": 2}
STATED = {"Layers": [{"name": "BEND_UP", "elements": 1}], "Properties": [{"metadata": {"angle": 90.0}}]}
ANNOTATED = [{"type": "LINE", "layer": "BEND_UP", "metadata": {"angle": 90.0}}]

# Something that is a shape envelope as far as the core is concerned - nothing
# here ever opens it - and large enough for the file cache to take it: geometry
# below 'cacheFilesMinEntrySize' is deliberately not stored, and an entry that
# was never written would prove nothing about what comes back from one.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n" + b"0" * (1 << 16)


class _Shape(Shape):
    """A shape built by a wrapper that recorded what it found, as they all do.

    'unbuilt=True' is a part whose script raised: no envelope, and so nothing
    recorded about it.
    """

    def __init__(self, measured=MEASURED, sections=None, annotations=None, unbuilt=False, name="thing"):
        """Named per test, so each one keys - and caches - on its own."""
        super().__init__("//test", {"name": name})
        self.name = name
        self.kind = "part"
        self._measured = measured
        self._sections = sections
        self._annotations = annotations
        self._unbuilt = unbuilt
        self.builds = 0
        self.hash.add_string("measurements-test-" + name)

    async def get_shape(self, ctx):
        """An envelope shaped as a wrapper hands one back, metadata and all."""
        self.builds += 1
        if self._unbuilt:
            return None
        envelope = {"name": self.name, "label": self.name, "brep": BREP}
        metadata = shape_envelope.make_metadata(
            measurements=self._measured,
            annotations=self._annotations,
            sections=self._sections,
        )
        if metadata:
            envelope[shape_envelope.KEY_METADATA] = metadata
        return envelope


@pytest.fixture
def ctx(tmp_path):
    """A context whose shape cache is this test's alone.

    The real one lives in the user's state directory and outlives the run, which
    would make "was this built again?" a question about every previous run.
    """
    (tmp_path / "partcad.yaml").write_text("name: //test\n")
    context = pc.Context(str(tmp_path))
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "cache"))
    return context


@pytest.fixture
def no_sandbox(monkeypatch):
    """Every sandbox measurement replaced by something that refuses to be called.

    Nothing in this file may start one. A measurement arrives with the geometry
    or it does not arrive, and a test that passes only because the core quietly
    started a process to fill a gap would be testing the design this replaced.
    """

    async def refuse(*args, **kwargs):
        raise AssertionError("the core measured on demand instead of at build time")

    # Patched on the module itself rather than on a name 'shape.py' holds,
    # because 'shape.py' does not hold one any more: it no longer imports
    # 'measure' at all, which is the strongest form this assertion has. The
    # patch is what would catch a lazy path being reintroduced.
    monkeypatch.setattr(pc_measure, "measurements", refuse)
    monkeypatch.setattr(pc_measure, "bbox", refuse)


#
# One entry, written once, holding the geometry and everything known about it
#


def test_the_numbers_arrive_with_the_geometry_and_no_sandbox_is_started(ctx, no_sandbox):
    """The design in one assertion: measuring is not a thing that happens later.

    The shape is built once; the size came back on its envelope. Asking for it
    again is a cache read, and at no point is a measuring process started - the
    fixture would fail the test if one were.
    """
    first = _Shape()
    assert asyncio.run(first.get_measurements_async(ctx)) == MEASURED
    assert first.builds == 1

    # A second object with the same key: what it gets is what the cache holds.
    second = _Shape()
    assert asyncio.run(second.get_measurements_async(ctx)) == MEASURED
    assert second.builds == 0


def test_the_geometry_and_what_is_known_about_it_are_one_entry(ctx, no_sandbox):
    """One key, and the suffixed siblings this replaced are not written.

    Separately-keyed entries can be separately present, which is three ways for
    one object's facts to disagree with its geometry. Reading the geometry key
    alone yields all of them.
    """
    shape = _Shape(sections=STATED, annotations=ANNOTATED, name="one-entry")
    asyncio.run(shape.get_wrapped(ctx))

    cached, _ = asyncio.run(ctx.cache_shapes.read_async(shape.hash, ["part"]))
    metadata = shape_envelope.metadata_of(cached["part"])

    assert shape_envelope.brep_bytes(cached["part"]["brep"]) == BREP
    assert metadata[shape_envelope.METADATA_MEASUREMENTS] == MEASURED
    assert metadata[shape_envelope.METADATA_SECTIONS] == STATED
    assert metadata[shape_envelope.METADATA_ANNOTATIONS] == ANNOTATED

    stale, _ = asyncio.run(ctx.cache_shapes.read_async(shape.hash, ["part-measure", "part-meta"]))
    assert stale.get("part-measure") is None
    assert stale.get("part-meta") is None


def test_the_brep_is_stored_byte_for_byte_behind_its_metadata():
    """Carrying metadata must not cost the geometry anything.

    A lone shape goes to the storage tier as the compressed frame the core
    already holds - no JSON, no base64, no re-encoding - and metadata is framed
    in front of it rather than wrapped around it. base64 would cost a third of
    the largest thing here to carry a few hundred bytes of the smallest.

    This asserts the **stored bytes**, not a round trip, and the difference is
    the whole point: base64 round-trips perfectly too. An earlier draft of this
    change sent every shape carrying metadata down the JSON path by accident,
    and every round-trip test passed while the cache grew by a third.
    """
    metadata = {shape_envelope.METADATA_MEASUREMENTS: MEASURED, shape_envelope.METADATA_SECTIONS: STATED}
    stored = cache_shape._serialize({"name": "n", "label": "l", "brep": BREP, "metadata": metadata})

    # Framed, and the geometry is the tail of it verbatim.
    assert stored.startswith(b"PCM1")
    assert stored.endswith(BREP)
    assert len(stored) - len(BREP) < 1024

    recovered = cache_shape._deserialize(stored)
    assert recovered["brep"] == BREP
    assert recovered["metadata"] == metadata


def test_a_shape_with_nothing_recorded_is_stored_as_bare_geometry():
    """No metadata, no frame: the bytes go to the tier exactly as they are."""
    assert cache_shape._serialize({"name": "n", "brep": BREP}) == BREP
    assert cache_shape._serialize({"name": "n", "brep": BREP, "metadata": {}}) == BREP


def test_a_shape_that_did_not_build_records_nothing(ctx, no_sandbox):
    """'pc info' on a part whose script raised is a common thing to do."""
    shape = _Shape(unbuilt=True, name="broken")

    assert asyncio.run(shape.get_measurements_async(ctx)) is None
    assert asyncio.run(shape.get_metadata_async(ctx)) is None
    assert asyncio.run(shape._reported_async(ctx)) == {}


def test_a_shape_nobody_measured_reports_nothing_rather_than_nought(ctx, no_sandbox):
    """A producer that recorded no size is not a shape of no size.

    The envelope carries no measurements section at all, and what comes back is
    None - not a box of zeroes, and not a volume of nought.
    """
    shape = _Shape(measured=None, sections=STATED, name="unmeasured")

    assert asyncio.run(shape.get_measurements_async(ctx)) is None
    assert asyncio.run(shape._reported_async(ctx))["Layers"] == STATED["Layers"]


#
# Across a transform, where the geometry changes and the source does not
#


SCALED = {"bbox": [-2.0, 0.0, 4.0, 18.0, 40.0, 10.0], "volume": 12000.0, "solids": 2}


def test_a_transform_replaces_the_measurements_and_keeps_the_sections(ctx, no_sandbox, monkeypatch):
    """'offset'/'scale' rebuild the geometry, so the size is the new one.

    The wrapper that applies them decodes an envelope and encodes a fresh one,
    measuring what came out - so the numbers arriving back are of the shape that
    now exists. What that wrapper cannot know is what the *source file* stated,
    which is still true of the object and has to survive the trip.
    """

    async def scale(ctx, shape, factor):
        """The transform wrapper, as far as this is concerned: new size, no sections."""
        return {
            "name": "scaled",
            "brep": BREP,
            shape_envelope.KEY_METADATA: {shape_envelope.METADATA_MEASUREMENTS: SCALED},
        }

    monkeypatch.setattr(pc.transform, "scale", scale)

    shape = _Shape(sections=STATED, name="scaled")
    shape.config["scale"] = 2.0
    asyncio.run(shape.get_wrapped(ctx))

    assert asyncio.run(shape.get_measurements_async(ctx)) == SCALED
    assert asyncio.run(shape._reported_async(ctx))["Layers"] == STATED["Layers"]


def test_a_transform_that_could_not_measure_reports_no_size_rather_than_the_old_one(ctx, no_sandbox, monkeypatch):
    """The size before a scale is the one answer nobody could detect as wrong.

    Merging fresh numbers over the old ones keeps the old ones when there are no
    fresh numbers, which would report a part scaled by two at its original size.
    So the old measurements are dropped before the merge, and a transform that
    came back with none leaves the shape honestly unmeasured.
    """

    async def scale(ctx, shape, factor):
        """A transform whose encoder could not measure what came out."""
        return {"name": "scaled", "brep": BREP}

    monkeypatch.setattr(pc.transform, "scale", scale)

    shape = _Shape(sections=STATED, name="unmeasurable-scale")
    shape.config["scale"] = 2.0
    asyncio.run(shape.get_wrapped(ctx))

    assert asyncio.run(shape.get_measurements_async(ctx)) is None
    # ...and what the file said is untouched by any of that.
    assert asyncio.run(shape._reported_async(ctx))["Layers"] == STATED["Layers"]


#
# What 'pc info' makes of it
#


def test_the_bounding_box_is_reported_as_where_it_is_and_how_large(ctx, no_sandbox):
    """Three triples: a shape 10 wide starting at -1 is not a shape 10 wide at 0.

    'size' is stated rather than left to be subtracted - it is the one of the
    three anybody reads out loud.
    """
    info = asyncio.run(_Shape()._reported_async(ctx))

    assert info["BoundingBox"] == {
        "min": [-1.0, 0.0, 2.0],
        "max": [9.0, 20.0, 5.0],
        "size": [10.0, 20.0, 3.0],
    }


def test_the_volume_and_how_many_solids_it_is_of(ctx, no_sandbox):
    """More than one solid in a part is worth saying: it is deliberate or a bug."""
    info = asyncio.run(_Shape()._reported_async(ctx))

    assert info["Volume"] == 1500.0
    assert info["Solids"] == 2


def test_a_shape_with_no_solid_in_it_has_no_volume_to_report(ctx, no_sandbox):
    """A sketch, a shell, a wire. Nought and "none to speak of" differ."""
    measured = {"bbox": [0.0, 0.0, 0.0, 10.0, 10.0, 0.0], "volume": None, "solids": 0}
    info = asyncio.run(_Shape(measured=measured, name="sheet")._reported_async(ctx))

    assert "Volume" not in info
    assert "Solids" not in info
    assert info["BoundingBox"]["size"] == [10.0, 10.0, 0.0]


def test_a_volume_that_is_negative_is_reported_as_it_stands(ctx, no_sandbox):
    """Faces oriented inward: a real thing to know, not a sign to drop."""
    measured = {"bbox": MEASURED["bbox"], "volume": -1500.0, "solids": 1}

    assert asyncio.run(_Shape(measured=measured, name="inverted")._reported_async(ctx))["Volume"] == -1500.0


def test_an_empty_bounding_box_is_left_out_rather_than_invented(ctx, no_sandbox):
    """A shape that built and occupies nothing has no size to state."""
    measured = {"bbox": None, "volume": None, "solids": 0}

    assert asyncio.run(_Shape(measured=measured, name="empty")._reported_async(ctx)) == {}


#
# ...and the sections, which the core reports without reading
#


def test_what_the_source_stated_is_merged_in_as_the_wrapper_named_it(ctx, no_sandbox):
    """Verbatim: the core has no vocabulary of its own to translate these into."""
    info = asyncio.run(_Shape(sections=STATED, name="stated")._reported_async(ctx))

    assert info["Layers"] == STATED["Layers"]
    assert info["Properties"] == STATED["Properties"]


def test_the_per_element_records_are_carried_but_not_reported(ctx, no_sandbox):
    """They reach the check that reads them, and 'pc info' does not list them.

    Choosing which elements are worth showing means reading into a record, and
    what a record holds is the producing wrapper's vocabulary. The wrapper
    reports the ones worth showing under a heading of its own; this half is
    carried for 'get_annotations_async' and left unopened.
    """
    shape = _Shape(annotations=ANNOTATED, name="annotated")

    assert asyncio.run(shape.get_annotations_async(ctx)) == ANNOTATED
    assert "Annotations" not in asyncio.run(shape._reported_async(ctx))


def test_it_is_read_back_without_building_again(ctx, no_sandbox):
    """A second object with the same key is answered from the one entry."""
    asyncio.run(_Shape(sections=STATED, name="shared").get_wrapped(ctx))

    second = _Shape(sections=STATED, name="shared")
    assert asyncio.run(second.get_metadata_async(ctx))[shape_envelope.METADATA_SECTIONS] == STATED
    assert second.builds == 0


def test_it_survives_a_run_with_nowhere_to_cache_it(ctx, no_sandbox):
    """'cache: false', or every tier switched off, is not "nothing was recorded".

    The object keeps what it learnt while building, because a run that cannot
    store it still has to be able to answer. Without that, 'pc info' on an
    uncacheable STEP part reports the file as stating nothing at all.
    """
    shape = _Shape(sections=STATED, name="uncached")
    shape.cacheable = False
    asyncio.run(shape.get_wrapped(ctx))

    cached, _ = asyncio.run(ctx.cache_shapes.read_async(shape.hash, ["part"]))
    assert cached.get("part") is None

    assert asyncio.run(shape.get_measurements_async(ctx)) == MEASURED
    assert asyncio.run(shape._reported_async(ctx))["Layers"] == STATED["Layers"]


def test_an_alias_answers_with_what_its_source_recorded(ctx, no_sandbox):
    """A reference shares its source's cache entry, and what it recorded with it."""
    source = _Shape(sections=STATED, name="source")
    asyncio.run(source.get_wrapped(ctx))

    alias = _Shape(measured=None, name="alias")
    alias.take_side_data_from(source)

    metadata = asyncio.run(alias.get_metadata_async(ctx))
    assert metadata[shape_envelope.METADATA_SECTIONS] == STATED
    assert metadata[shape_envelope.METADATA_MEASUREMENTS] == MEASURED


def test_a_shape_whose_type_reads_no_file_states_nothing(ctx, no_sandbox):
    """It still has a size; it simply has no source with anything to say."""
    shape = _Shape(name="silent")

    info = asyncio.run(shape._reported_async(ctx))
    assert "Layers" not in info
    assert info["Volume"] == 1500.0
