#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a drawing says about its own elements, and how it survives the trip.

A DXF entity may carry XDATA - tags an application wrote against it, beside the
geometry - and that is where a sheet metal drawing says which line is a bend and
how far it goes. BREP has nowhere to put any of it, so it is read as the file is
imported ('wrappers/dxf_metadata.py') and carried beside the geometry from then
on, which is what makes it a property of the *sketch* rather than of the file:
the day another sketch type states the same thing, nothing that reads it changes.

A drawing also says things about *itself* - which layers it has, what its
numbers are in, which application wrote it - and that is read on the same trip,
for a reason of its own: a sketch is the layers its filters selected, and the
interesting thing about the ones they did not select is that they exist. It
travels a different road from here, on the envelope beside the BREP rather than
on the sketch, so what is checked of it here is the reading alone.

Two halves are checked here, and they are the two the feature is made of:

* the reading - which spellings of XDATA are understood, which elements are
  reported, what the layer filters do to the answer, and what the drawing says
  about itself;
* the carrying - that the annotations are cached beside the geometry, and that a
  cache entry written before they existed is rebuilt rather than read back as a
  drawing that annotates nothing.

No CAD library and no sandbox: the reader needs ezdxf alone, and the caching is
exercised through 'Shape.get_wrapped' over a shape that builds nothing.
"""

import asyncio
import hashlib
import os
import sys

import ezdxf
import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import cache_hash as cache_hash_module
from partcad import shape_envelope
from partcad.cache_hash import CacheHash
from partcad.cache_shape import ShapeCache
from partcad.sketch import Sketch

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import dxf_metadata  # noqa: E402


def _drawing(tmp_path, name="bends.dxf"):
    """A drawing with a bend up, a bend down, and an outline that is neither."""
    document = ezdxf.new("R2010")
    document.appids.new("PARTCAD")
    modelspace = document.modelspace()

    # Written as one string tag per pair, which is what an application with only
    # strings to write produces.
    up = modelspace.add_line((0, 0), (10, 0), dxfattribs={"layer": "BEND_UP"})
    up.set_xdata("PARTCAD", [(1000, "angle=90"), (1000, "radius=1.5"), (1000, "DIRECTION=Up")])

    # ...and as a name followed by a typed value, which is what an application
    # that cares about the type of a number writes.
    down = modelspace.add_line((0, 5), (10, 5), dxfattribs={"layer": "BEND_DOWN"})
    down.set_xdata(
        "PARTCAD",
        [(1000, "angle"), (1040, 30.0), (1000, "radius"), (1040, 2.0), (1000, "direction"), (1000, "down")],
    )

    modelspace.add_lwpolyline([(0, -2), (10, -2), (10, 8), (0, 8)], close=True, dxfattribs={"layer": "OUTLINE"})

    path = str(tmp_path / name)
    document.saveas(path)
    return path


#
# Reading what the drawing says
#


def test_both_spellings_of_extended_data_are_read(tmp_path):
    """One tag holding 'key=value', and a name followed by a typed value."""
    annotations = dxf_metadata.read(_drawing(tmp_path))
    by_layer = {a["layer"]: a for a in annotations}

    assert by_layer["BEND_UP"]["metadata"] == {"angle": "90", "radius": "1.5", "direction": "Up"}
    assert by_layer["BEND_DOWN"]["metadata"] == {"angle": 30.0, "radius": 2.0, "direction": "down"}


def test_a_key_is_read_whatever_case_it_is_written_in(tmp_path):
    """'DIRECTION' and 'direction' are the one key they were meant to be.

    The value is left exactly as the file states it: 'Up' stays 'Up', and
    whoever reads it decides what counts as up.
    """
    annotations = dxf_metadata.read(_drawing(tmp_path))
    up = next(a for a in annotations if a["layer"] == "BEND_UP")
    assert "direction" in up["metadata"]
    assert up["metadata"]["direction"] == "Up"


def test_an_element_with_no_extended_data_is_still_reported(tmp_path):
    """A drawing that annotates nothing differs from a line left un-annotated.

    A check that every bend line says how far it bends has to be able to tell
    them apart, so an un-annotated element is a record with empty metadata
    rather than no record at all.
    """
    annotations = dxf_metadata.read(_drawing(tmp_path))
    outline = next(a for a in annotations if a["layer"] == "OUTLINE")
    assert outline["metadata"] == {}
    assert outline["type"] == "LWPOLYLINE"


def test_an_element_is_located_and_identified(tmp_path):
    """Enough to trace a record back to the entity it came from, and to place it."""
    annotations = dxf_metadata.read(_drawing(tmp_path))
    up = next(a for a in annotations if a["layer"] == "BEND_UP")
    assert up["type"] == "LINE"
    assert up["points"] == [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]
    assert up["handle"]


def test_the_layer_filters_decide_which_elements_are_described(tmp_path):
    """The annotations describe what is in the sketch, not what was filtered out.

    The same rule the import applies, and it has to be: a record for a layer the
    sketch does not read would describe a bend along a line that is not there.
    """
    path = _drawing(tmp_path)

    included = dxf_metadata.read(path, include=["BEND_UP", "BEND_DOWN"])
    assert sorted(a["layer"] for a in included) == ["BEND_DOWN", "BEND_UP"]

    excluded = dxf_metadata.read(path, exclude=["OUTLINE"])
    assert sorted(a["layer"] for a in excluded) == ["BEND_DOWN", "BEND_UP"]

    assert len(dxf_metadata.read(path)) == 3


def test_each_selection_of_layers_describes_its_own_elements(tmp_path):
    """One layer, the other layer, and the two together - three different answers.

    The drawing is read once per reference that asks for it, and each reading
    has to answer for the elements *it* selected: a bend line the reference left
    out is a bend along a line that is not in that sketch.
    """
    path = _drawing(tmp_path)
    readings = [
        dxf_metadata.read(path, include=["BEND_UP"]),
        dxf_metadata.read(path, include=["BEND_DOWN"]),
        dxf_metadata.read(path, include=["BEND_UP", "BEND_DOWN"]),
    ]
    assert [len(reading) for reading in readings] == [1, 1, 2]
    assert [sorted(a["layer"] for a in reading) for reading in readings] == [
        ["BEND_UP"],
        ["BEND_DOWN"],
        ["BEND_DOWN", "BEND_UP"],
    ]
    # Distinct down to the handles, so no reading is another one's answer.
    handles = [tuple(sorted(a["handle"] for a in reading)) for reading in readings]
    assert len(set(handles)) == len(handles)


def test_a_bare_number_names_nothing(tmp_path):
    """A value with no name in front of it is not a key/value pair."""
    document = ezdxf.new("R2010")
    document.appids.new("PARTCAD")
    line = document.modelspace().add_line((0, 0), (1, 0))
    line.set_xdata("PARTCAD", [(1040, 90.0), (1000, "radius"), (1040, 1.0)])
    path = str(tmp_path / "odd.dxf")
    document.saveas(path)

    assert dxf_metadata.read(path)[0]["metadata"] == {"radius": 1.0}


#
# Carrying it beside the geometry
#


# Something that is a shape envelope as far as the core is concerned - nothing
# here ever opens it - and large enough for the file cache to take it: geometry
# below 'cacheFilesMinEntrySize' is deliberately not stored, and an entry that
# was never written would prove nothing about what comes back from one.
BREP = b"CASCADE Topology V3, (c) Open Cascade\n" + b"0" * (1 << 16)


class _CountingSketch(Sketch):
    """A sketch that records what its drawing said, and counts the times it read it.

    What it returns is what a real import wrapper returns: one envelope, with
    the annotations on it under the protocol's own section. There is no second
    channel to set anything on, which is the point - a factory that wanted one
    would have to invent it.
    """

    def __init__(self, project_name, config, annotations):
        super().__init__(project_name, config)
        self._annotations = annotations
        self.builds = 0

    async def get_shape(self, ctx):
        self.builds += 1
        envelope = {"name": self.name, "label": self.name, "brep": BREP}
        metadata = shape_envelope.make_metadata(annotations=self._annotations)
        if metadata:
            envelope[shape_envelope.KEY_METADATA] = metadata
        return envelope


@pytest.fixture
def ctx(tmp_path):
    """A context whose shape cache is this test's alone.

    The real one lives in the user's state directory and outlives the run, which
    is the whole point of it - and which would make "was this built again?" a
    question about every previous run rather than about this one.
    """
    (tmp_path / "partcad.yaml").write_text("name: //test\n")
    context = pc.Context(str(tmp_path))
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "cache"))
    return context


def _sketch(ctx, annotations, name="bends"):
    sketch = _CountingSketch("//test", {"name": name, "type": "dxf"}, annotations)
    sketch.hash.add_string("annotations-test-" + name)
    return sketch


def test_annotations_come_back_with_the_cached_geometry(ctx):
    """Built once, answered from the cache after that - annotations included.

    They are cached because they have to be: a sketch that comes out of the
    cache is never instantiated, so annotations that were only ever set while
    building would be silently empty for every run but the first.

    And they come back out of the *same* entry the geometry does, which is what
    makes one cache hit the whole answer.
    """
    annotations = [{"type": "LINE", "layer": "BEND_UP", "metadata": {"angle": 90.0}}]
    first = _sketch(ctx, annotations)
    assert asyncio.run(first.get_annotations(ctx)) == annotations
    assert first.builds == 1

    # A second object with the same key: what it gets is what the cache holds.
    second = _sketch(ctx, [])
    assert asyncio.run(second.get_annotations(ctx)) == annotations
    assert second.builds == 0


def test_the_geometry_entry_is_the_only_entry(ctx):
    """One key, holding the geometry and everything recorded about it.

    The annotations used to be a sibling entry keyed on the same hash with a
    suffix, which is two entries that can be separately present for one object.
    Reading the geometry key alone now yields both halves, and no other key is
    written for the sketch at all.
    """
    annotations = [{"type": "LINE", "layer": "BEND_UP", "metadata": {"angle": 90.0}}]
    sketch = _sketch(ctx, annotations, name="one-entry")
    asyncio.run(sketch.get_wrapped(ctx))

    cached, _ = asyncio.run(ctx.cache_shapes.read_async(sketch.hash, ["sketch"]))
    entry = cached["sketch"]
    assert shape_envelope.brep_bytes(entry["brep"]) == BREP
    assert (
        shape_envelope.metadata_section(shape_envelope.metadata_of(entry), shape_envelope.METADATA_ANNOTATIONS)
        == annotations
    )

    # Nothing under the suffixes this used to be split across.
    stale, _ = asyncio.run(ctx.cache_shapes.read_async(sketch.hash, ["annotations", "sketch-meta"]))
    assert stale.get("annotations") is None
    assert stale.get("sketch-meta") is None


def test_a_sketch_that_says_nothing_records_that_it_said_nothing(ctx):
    """An empty entry is an answer; a missing one is a question never asked.

    Without writing the empty one, a sketch whose drawing annotates nothing
    would be rebuilt on every run looking for annotations it never had.
    """
    first = _sketch(ctx, [], name="plain")
    assert asyncio.run(first.get_annotations(ctx)) == []
    assert first.builds == 1

    second = _sketch(ctx, [], name="plain")
    assert asyncio.run(second.get_annotations(ctx)) == []
    assert second.builds == 0


def _seeded(version, data):
    """A cache key as PartCAD of that format version would have computed it."""
    hasher = hashlib.md5()
    hasher.update(("partcad-cache-v%d" % version).encode())
    cache_hash = CacheHash("//test:upgrade", hasher=hasher, cache=True)
    cache_hash.add_string(data)
    return cache_hash


def test_a_key_is_seeded_with_the_cache_format_version():
    """The mechanism the upgrade below rests on, asserted against the real thing.

    A hash built the ordinary way has to match one seeded by hand with the
    *current* version tag, and differ from one seeded with the previous. The
    first half is what fails if the seeding is ever dropped or mis-spelled -
    comparing two hand-seeded hashes would only ever prove that md5 tells two
    inputs apart.
    """
    data = "a sketch that was cached before any of this existed"

    ordinary = CacheHash("//test:upgrade", cache=True)
    ordinary.add_string(data)

    assert ordinary.get() == _seeded(cache_hash_module.VERSION, data).get()
    assert ordinary.get() != _seeded(cache_hash_module.VERSION - 1, data).get()


def test_a_geometry_only_entry_is_never_read_back_as_one_that_recorded_nothing(ctx):
    """The upgrade case, and why it is a cache *version* rather than a check.

    A sketch cached by an older PartCAD holds valid geometry and nothing else,
    and nothing in that entry distinguishes "this drawing annotates nothing"
    from "nobody recorded what it annotates". The first is an answer a
    manufacturability check acts on; the second is not an answer at all.

    Rather than teach every reader to tell them apart, the entry is not read:
    the version seeds every hash, so what the old run wrote is never looked up
    again.
    """
    data = "a sketch that was cached before any of this existed"
    old = _seeded(cache_hash_module.VERSION - 1, data)

    # Exactly what the previous format wrote: the geometry, alone.
    asyncio.run(ctx.cache_shapes.write_async(old, {"sketch": {"brep": BREP}}))

    # It is there under the key it went in under...
    written, _ = asyncio.run(ctx.cache_shapes.read_async(old, ["sketch"]))
    assert written["sketch"] is not None

    # ...and unreachable under the one this version asks with, so "recorded
    # nothing" is never what a reader is told.
    current = CacheHash("//test:upgrade", cache=True)
    current.add_string(data)
    cached, _ = asyncio.run(ctx.cache_shapes.read_async(current, ["sketch"]))
    assert cached.get("sketch") is None


def test_the_cache_version_was_moved_for_this_change(ctx):
    """The entry format changed, so the version had to, and this says so out loud.

    Without the bump, a v3 entry - geometry and nothing else - would be read
    back under an unchanged key and reported as a drawing that annotates
    nothing.
    """
    assert cache_hash_module.VERSION >= 4


#
# What the drawing says about itself, rather than about any of its elements
#


def test_the_layers_include_the_ones_this_sketch_does_not_read(tmp_path):
    """The point of reporting a layer that was filtered out is that it exists.

    A layer filter that matched nothing and a layer that is not in the file both
    produce a sketch with nothing in it, and this is what tells them apart.
    """
    document = ezdxf.readfile(_drawing(tmp_path))
    described = dxf_metadata.describe(document, include=["BEND_UP"])
    by_name = {layer["name"]: layer for layer in described["layers"]}

    assert by_name["BEND_UP"]["read"] is True
    assert by_name["BEND_DOWN"]["read"] is False
    assert by_name["OUTLINE"]["read"] is False


def test_a_layer_says_how_much_is_on_it_and_of_what(tmp_path):
    """Per layer and per entity type, including a layer nothing is drawn on."""
    document = ezdxf.readfile(_drawing(tmp_path))
    by_name = {layer["name"]: layer for layer in dxf_metadata.describe(document)["layers"]}

    assert by_name["BEND_UP"]["elements"] == 1
    assert by_name["BEND_UP"]["types"] == {"LINE": 1}
    assert by_name["OUTLINE"]["types"] == {"LWPOLYLINE": 1}
    # Declared by the table and drawn on by nothing, which is still a layer.
    assert by_name["0"]["elements"] == 0


def test_what_the_drawing_says_about_itself(tmp_path):
    """Which DXF it is, how much it holds, and who could have annotated it."""
    document = ezdxf.readfile(_drawing(tmp_path))
    described = dxf_metadata.describe(document)

    assert described["release"] == "R2010"
    assert described["elements"] == 3
    # XDATA is written under an APPID, so the ones the file declares are the
    # names an annotation could have come from.
    assert "PARTCAD" in described["appids"]


def test_the_units_are_what_the_drawing_states(tmp_path):
    """PartCAD reads a DXF as millimetres; what the file says is worth seeing."""
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = 1
    document.modelspace().add_line((0, 0), (1, 0))
    path = str(tmp_path / "inches.dxf")
    document.saveas(path)

    assert dxf_metadata.read_file(path)["metadata"]["Drawing"]["units"] == "in"


def test_the_us_survey_units_are_units(tmp_path):
    """Codes 21-24, which AutoCAD added long after the first twenty.

    A code the table does not have used to come back as None, which is what a
    drawing that states it is *unitless* comes back as - so a survey drawing
    read as having no units at all, which is a wrong answer rather than a
    missing one.
    """
    for code, name in ((21, "us-ft"), (22, "us-in"), (23, "us-yd"), (24, "us-mi")):
        document = ezdxf.new("R2010")
        document.header["$INSUNITS"] = code
        document.modelspace().add_line((0, 0), (1, 0))
        path = str(tmp_path / ("survey-%d.dxf" % code))
        document.saveas(path)

        assert dxf_metadata.read_file(path)["metadata"]["Drawing"]["units"] == name


def test_a_unit_this_does_not_know_is_not_no_unit(tmp_path):
    """DXF has gained units before and will again, and the two must not merge.

    Reported as the code it is, so a drawing read by a PartCAD that predates its
    unit says something a reader can act on rather than reading as unitless.
    """
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = 97
    document.modelspace().add_line((0, 0), (1, 0))
    path = str(tmp_path / "from-the-future.dxf")
    document.saveas(path)

    assert dxf_metadata.read_file(path)["metadata"]["Drawing"]["units"] == "unknown (97)"


def test_a_drawing_that_says_it_is_unitless(tmp_path):
    """'unitless' is not 'millimetres', and reporting it as one would be a guess."""
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = 0
    document.modelspace().add_line((0, 0), (1, 0))
    path = str(tmp_path / "unitless.dxf")
    document.saveas(path)

    assert dxf_metadata.read_file(path)["metadata"]["Drawing"]["units"] is None


def test_one_pass_over_the_file_answers_both_questions(tmp_path):
    """'read_file' is 'describe' and 'read' of one opening of the drawing."""
    path = _drawing(tmp_path)
    read = dxf_metadata.read_file(path, include=["BEND_UP"])

    assert [a["layer"] for a in read["annotations"]] == ["BEND_UP"]
    # ...and under the headings 'pc info' prints them with, which is the
    # reader's to choose: the core merges what a wrapper hands it verbatim.
    assert set(read["metadata"]) == {"Annotations", "Drawing", "Layers"}
    assert len(read["metadata"]["Layers"]) == len(dxf_metadata.describe(ezdxf.readfile(path))["layers"])


#
# ...and which of them a reader is shown, which the *wrapper* decides
#


def test_the_annotated_elements_are_what_pc_info_lists(tmp_path):
    """An 'angle' and a 'radius' against a bend line, and no un-annotated lines.

    Chosen here, in the module that reads the drawing, rather than by the core:
    picking the annotated records out means knowing that a record has a
    'metadata' key and that an empty one means un-annotated, which is this
    format's vocabulary. The core reports the section verbatim and never opens a
    record - so 'Annotations' is a heading this module chose, exactly like
    'Layers' and 'Drawing' beside it.
    """
    read = dxf_metadata.read_file(_drawing(tmp_path))

    listed = read["metadata"]["Annotations"]
    assert [record["layer"] for record in listed] == ["BEND_UP", "BEND_DOWN"]
    # Values exactly as the file states them: this bend is written as string
    # tags, so its angle is the text "90" and not the number 90.0. The one
    # beside it is written as typed tags and comes back typed.
    assert listed[0]["metadata"] == {"angle": "90", "radius": "1.5", "direction": "Up"}
    assert listed[1]["metadata"] == {"angle": 30.0, "radius": 2.0, "direction": "down"}

    # ...while the full list, which the manufacturability check reads, still
    # holds the un-annotated element that is deliberately not listed above.
    assert any(not record["metadata"] for record in read["annotations"])


def test_a_drawing_that_annotates_nothing_lists_no_elements(tmp_path):
    """No section at all, rather than an empty one.

    An empty 'Annotations' heading in 'pc info' would read as a drawing whose
    elements were examined and found bare, which is what it is - but the
    heading costs a reader a line to discover it says nothing.
    """
    document = ezdxf.new("R2010")
    document.modelspace().add_line((0, 0), (1, 0))
    path = str(tmp_path / "bare.dxf")
    document.saveas(path)

    read = dxf_metadata.read_file(path)
    assert read["annotations"]
    assert "Annotations" not in read["metadata"]
