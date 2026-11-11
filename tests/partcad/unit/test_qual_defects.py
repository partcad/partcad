#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'defects' on 'data/qual_defects', as the Topology tab asks it.

What 'validity' and 'degenerate' say of a whole part, this says of its pieces,
and shows them: the free edges of a box with a face missing, the slivers of a
block fused badly, and nothing at all of a box that is well made. Checked in shards, as a large
shape is, it says and shows exactly the same.
"""

import asyncio

import pytest

import partcad as pc
from partcad import shape_envelope
from partcad.qual import highlight, report
from partcad.qual.topology import defects

PACKAGE = "tests/partcad/unit/data/qual_defects/partcad.yaml"


@pytest.fixture
def ctx():
    # Asked afresh: a verdict another run left in the cache says what it found
    # in that run's words, and a pass it left says nothing at all.
    config = pc.UserConfig()
    config.cache_bypass = True
    return pc.Context(PACKAGE, user_config=config)


def _defects(ctx, name, verify=True):
    part = ctx.get_part("//:%s" % name)
    results = asyncio.run(report.run_async(ctx, part, verify=verify, subtypes=["topology"]))
    return {result.name: result for result in results}["defects"]


def test_it_is_a_topology_check_that_does_not_ask_an_assembly(ctx):
    result = _defects(ctx, "sound", verify=False)
    assert result.subtype == "topology"


def test_a_well_made_part_passes_with_nothing_left_behind(ctx):
    result = _defects(ctx, "sound")
    assert result.status == report.PASSED
    assert "well formed" in result.findings[0]["text"]
    assert result.artifacts == []


def test_the_free_edges_of_a_hole_are_reported_and_shown_but_not_failed(ctx):
    result = _defects(ctx, "open_box")
    assert result.status == report.WARNED
    text = result.findings[0]["text"]
    assert "4 of its 12 edges are defective" in text
    assert "4 edges bound one face only" in text
    # What belongs to no one edge: the shell, which the hole leaves open.
    assert "NotClosed" in text
    (artifact,) = result.artifacts
    assert artifact["name"] == "open_box/defects"
    assert artifact[highlight.FOCUS_KEY] == highlight.FOCUS
    labels = [feature["label"] for feature in artifact[highlight.FEATURES_KEY]]
    assert len(labels) == 4 and all(label.startswith("edge ") and "free" in label for label in labels)
    edges = ctx.get_part("//:open_box/defects/focus/edges")
    assert edges.config["properties"]["color"] == highlight.COLORS["edge"]
    # The edges only: no face of the box is at fault.
    assert ctx.get_part("//:open_box/defects/focus/faces") is None


def test_slivers_are_the_pieces_thinner_than_the_threshold(ctx):
    result = _defects(ctx, "sliver")
    assert result.status == report.WARNED
    text = result.findings[0]["text"]
    assert "4 of its 14 faces and 4 of its 28 edges are defective" in text
    assert "8 slivers thinner than 0.001 mm" in text
    (artifact,) = result.artifacts
    features = artifact[highlight.FEATURES_KEY]
    assert any(feature["label"].startswith("face ") and "a sliver" in feature["label"] for feature in features)
    # Each pinned where it is: on the side of the block the slivers run along.
    assert all(abs(feature["at"][1] - 10.0) < 0.01 for feature in features)


def test_a_threshold_below_the_slivers_lets_them_pass(ctx):
    result = _defects(ctx, "sliver_tolerated")
    assert result.status == report.PASSED
    assert result.artifacts == []


def _verdict_and_drawing(name, shard_threshold, monkeypatch):
    """The verdict on 'name', in shards when its BREP is 'shard_threshold' bytes or more, and what it drew, as BREP."""
    monkeypatch.setattr(defects, "SHARD_THRESHOLD", shard_threshold)
    monkeypatch.setattr(defects, "SHARD_BYTES", 1)
    config = pc.UserConfig()
    config.cache_bypass = True
    ctx = pc.Context(PACKAGE, user_config=config)
    result = _defects(ctx, name)
    drawn = {}
    for kind in ("faces", "edges"):
        part = ctx.get_part("//:%s/defects/focus/%s" % (name, kind))
        if part is not None:
            envelope = asyncio.run(part.get_wrapped(ctx))
            drawn[kind] = shape_envelope.brep_plain(envelope[shape_envelope.KEY_BREP])
    return result.status, result.findings, result.artifacts, drawn


@pytest.mark.parametrize("name", ["open_box", "sliver", "sound"])
def test_checked_in_shards_the_verdict_and_what_it_draws_are_the_same(name, monkeypatch):
    # Every shape here is a few kilobytes: a threshold of nothing and a shard
    # per byte has it checked in as many shards as there are process slots.
    assert defects.sandbox_lock.process_slots.count >= 2
    whole = _verdict_and_drawing(name, 1 << 40, monkeypatch)
    sharded = _verdict_and_drawing(name, 0, monkeypatch)
    assert sharded == whole


def test_a_shape_is_sharded_by_the_size_of_its_brep_and_no_more_than_there_are_slots(monkeypatch):
    monkeypatch.setattr(defects.sandbox_lock.process_slots, "_count", 6)

    def envelope(size, shared=1):
        node = {shape_envelope.KEY_BREP: b"x" * size}
        # A payload shared by several nodes is one shape's, and counted once.
        return {"children": [node] * shared} if shared > 1 else node

    assert defects.payload_size(envelope(1000, shared=3)) == 1000
    assert defects.shard_count(envelope(defects.SHARD_THRESHOLD - 1)) == 1
    assert defects.shard_count(envelope(defects.SHARD_THRESHOLD)) == defects.SHARD_THRESHOLD // defects.SHARD_BYTES
    # Five payloads of their own, each the size of a shard.
    assert (
        defects.shard_count({"children": [{shape_envelope.KEY_BREP: b"x" * defects.SHARD_BYTES} for _ in range(5)]})
        == 5
    )
    assert defects.shard_count(envelope(100 * defects.SHARD_BYTES)) == 6
