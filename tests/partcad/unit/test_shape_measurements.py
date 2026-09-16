#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How big a shape is and how much of it there is, as 'pc info' reports it.

Two numbers a reader of a part wants before any other, and neither of them can
be read off a declaration: a part is a script, a file or a boolean of two
others, so the only way to know its size is to have built it. That is why they
are in 'pc info' at all, and why `/pc:describe` starts from them rather than
from a projection somebody estimated a size off.

The measuring itself is OCCT's and happens in the sandbox
('wrappers/wrapper_measure.py'), which is not reachable from here. What is
covered here is everything around it: that the answer is cached in an entry of
its own under the geometry's hash and the sandbox is not started twice for it,
that a shape which did not build is not measured and a failure is not
remembered, and which keys the numbers become for 'pc info'.

The second half of what 'pc info' adds travels the same rails in the other
direction: what the *file* said, which the wrapper that read it puts on the
envelope beside the BREP and the core stores in an entry of its own without ever
looking inside it. That trip is checked here too, because it is the core's half
of it - the reading itself belongs to 'test_step_metadata' and
'test_sketch_annotations'.
"""

import asyncio

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad.cache_shape import ShapeCache, measurements_key, metadata_key
from partcad.shape import Shape

MEASURED = {"bbox": [-1.0, 0.0, 2.0, 9.0, 20.0, 5.0], "volume": 1500.0, "solids": 2}


class _Shape(Shape):
    """A shape that never builds geometry and never reaches a sandbox."""

    def __init__(self, unbuilt=False, name="thing"):
        """Named per test, so each one keys - and caches - on its own."""
        super().__init__("//test", {"name": name})
        self.name = name
        self.kind = "part"
        self._unbuilt = unbuilt
        self.hash.add_string("measurements-test-" + name)

    async def get_wrapped(self, ctx):
        """Something opaque, or nothing for a shape whose script raised."""
        return None if self._unbuilt else {"brep": b"not looked at"}


@pytest.fixture
def ctx(tmp_path):
    """A context whose shape cache is this test's alone.

    The real one lives in the user's state directory and outlives the run, which
    would make "was this measured again?" a question about every previous run.
    """
    (tmp_path / "partcad.yaml").write_text("name: //test\n")
    context = pc.Context(str(tmp_path))
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "cache"))
    return context


@pytest.fixture
def sandbox(monkeypatch):
    """The sandbox, replaced by something that counts and starts no process."""

    async def measurements(ctx, shape):
        """What 'measure.measurements' would have started a process to answer."""
        sandbox.calls += 1
        if sandbox.raises:
            raise sandbox.raises
        return sandbox.result

    sandbox.calls = 0
    sandbox.raises = None
    sandbox.result = MEASURED
    monkeypatch.setattr(pc.shape.measure, "measurements", measurements)
    return sandbox


#
# The cache entry, which is what makes this affordable to ask
#


def test_the_sandbox_is_asked_once_and_the_answer_is_kept(ctx, sandbox):
    """Measured on the first ask, read back on every one after it.

    An entry of its own under the geometry's hash: the numbers are derived from
    the geometry, so they are exactly as valid as the entry they are named
    after, and reading them back costs a file where measuring costs a process.
    """
    first = _Shape()
    assert asyncio.run(first.get_measurements_async(ctx)) == MEASURED
    assert sandbox.calls == 1

    # A second object with the same key: what it gets is what the cache holds.
    second = _Shape()
    assert asyncio.run(second.get_measurements_async(ctx)) == MEASURED
    assert sandbox.calls == 1


def test_the_entry_is_the_geometry_key_with_a_suffix(ctx, sandbox):
    """Named after the geometry it describes, and read without pulling it.

    'read_async' is given that key alone, so asking how big a part is never
    materializes its BREP.
    """
    shape = _Shape()
    asyncio.run(shape.get_measurements_async(ctx))

    key = measurements_key("part")
    assert key == "part-measure"
    cached, _ = asyncio.run(ctx.cache_shapes.read_async(shape.hash, [key]))
    assert cached[key] == MEASURED


def test_a_shape_that_did_not_build_is_not_measured(ctx, sandbox):
    """'pc info' on a part whose script raised is a common thing to do."""
    shape = _Shape(unbuilt=True)

    assert asyncio.run(shape.get_measurements_async(ctx)) is None
    assert sandbox.calls == 0


def test_a_failure_to_measure_is_reported_and_not_remembered(ctx, sandbox):
    """About the machine rather than the shape - a sandbox not built yet.

    Caching it would answer every later run with this run's bad luck, so the
    next ask starts a sandbox again.
    """
    sandbox.raises = Exception("no sandbox")
    assert asyncio.run(_Shape().get_measurements_async(ctx)) is None

    sandbox.raises = None
    assert asyncio.run(_Shape().get_measurements_async(ctx)) == MEASURED
    assert sandbox.calls == 2


#
# What 'pc info' makes of the answer
#


def test_the_bounding_box_is_reported_as_where_it_is_and_how_large(ctx, sandbox):
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


def test_the_volume_and_how_many_solids_it_is_of(ctx, sandbox):
    """More than one solid in a part is worth saying: it is deliberate or a bug."""
    info = asyncio.run(_Shape()._reported_async(ctx))

    assert info["Volume"] == 1500.0
    assert info["Solids"] == 2


def test_a_shape_with_no_solid_in_it_has_no_volume_to_report(ctx, sandbox):
    """A sketch, a shell, a wire. Nought and "none to speak of" differ."""
    sandbox.result = {"bbox": [0.0, 0.0, 0.0, 10.0, 10.0, 0.0], "volume": None, "solids": 0}
    info = asyncio.run(_Shape()._reported_async(ctx))

    assert "Volume" not in info
    assert "Solids" not in info
    assert info["BoundingBox"]["size"] == [10.0, 10.0, 0.0]


def test_a_volume_that_is_negative_is_reported_as_it_stands(ctx, sandbox):
    """Faces oriented inward: a real thing to know, not a sign to drop."""
    sandbox.result = {"bbox": MEASURED["bbox"], "volume": -1500.0, "solids": 1}

    assert asyncio.run(_Shape()._reported_async(ctx))["Volume"] == -1500.0


def test_an_empty_bounding_box_is_left_out_rather_than_invented(ctx, sandbox):
    """A shape that built and occupies nothing has no size to state."""
    sandbox.result = {"bbox": None, "volume": None, "solids": 0}

    assert asyncio.run(_Shape()._reported_async(ctx)) == {}


def test_a_shape_that_cannot_be_measured_costs_pc_info_nothing_else(ctx, sandbox):
    """It still has a configuration, a hash and its dependencies to report."""
    sandbox.raises = Exception("no sandbox")

    assert asyncio.run(_Shape()._reported_async(ctx)) == {}


#
# ...and the other half: what the file said, carried on the envelope
#


# Something that is a shape envelope as far as the core is concerned - nothing
# here ever opens it - and large enough for the file cache to take it.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n" + b"0" * (1 << 16)

STATED = {"Layers": [{"name": "BEND_UP", "elements": 1}], "Properties": [{"metadata": {"angle": 90.0}}]}


class _ImportedShape(Shape):
    """A shape built by a wrapper that read a file and said what it found."""

    def __init__(self, metadata=STATED, name="imported"):
        """'metadata=None' is a shape whose type reads no file at all."""
        super().__init__("//test", {"name": name})
        self.name = name
        self.kind = "part"
        self._metadata = metadata
        self.builds = 0
        self.hash.add_string("metadata-test-" + name)

    async def get_shape(self, ctx):
        """An envelope shaped as a wrapper hands one back, metadata and all."""
        self.builds += 1
        envelope = {"name": self.name, "label": self.name, "brep": BREP}
        if self._metadata is not None:
            envelope["metadata"] = self._metadata
        return envelope


def test_what_the_file_said_is_stored_in_an_entry_of_its_own(ctx, sandbox):
    """Off the envelope on the way past, into the key named after the geometry.

    The core never looks inside it: the sections are the wrapper's own
    vocabulary, and which format answered is not a question the core asks.
    """
    shape = _ImportedShape()
    asyncio.run(shape.get_wrapped(ctx))

    key = metadata_key("part")
    assert key == "part-meta"
    cached, _ = asyncio.run(ctx.cache_shapes.read_async(shape.hash, [key]))
    assert cached[key] == STATED


def test_it_is_read_back_without_pulling_the_geometry(ctx, sandbox):
    """Which is the point of the separate entry: 'pc info' wants what was said.

    A second object with the same key gets it without building, and 'pc info'
    merges the sections in as the wrapper named them.
    """
    asyncio.run(_ImportedShape().get_wrapped(ctx))

    second = _ImportedShape()
    assert asyncio.run(second.get_cached_metadata_async(ctx)) == STATED
    assert second.builds == 0
    assert asyncio.run(second._reported_async(ctx))["Layers"] == STATED["Layers"]


def test_a_shape_whose_type_reads_no_file_states_nothing(ctx, sandbox):
    """No entry is written, and a missing one is not a reason to build again."""
    shape = _ImportedShape(metadata=None, name="silent")
    asyncio.run(shape.get_wrapped(ctx))

    assert asyncio.run(shape.get_cached_metadata_async(ctx)) is None
    assert "Layers" not in asyncio.run(shape._reported_async(ctx))
