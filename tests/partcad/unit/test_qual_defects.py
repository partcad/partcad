#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'defects' on 'data/qual_defects', as the Topology tab asks it.

What 'validity' and 'degenerate' say of a whole part, this says of its pieces,
and shows them: the free edges of a box with a face missing, the slivers of a
block fused badly, and nothing at all of a box that is well made.
"""

import asyncio

import pytest

import partcad as pc
from partcad.qual import highlight, report

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


def _found(**overrides):
    """What the wrapper answers, for a part of 100 faces and 2000 edges with nothing wrong, changed by 'overrides'."""
    found = {
        "success": True,
        "valid": True,
        "faces": 100,
        "edges": 2000,
        "defective_faces": 0,
        "defective_edges": 0,
        "free": 0,
        "slivers": 0,
        "whole": [],
        "whole_faces": False,
        "whole_edges": False,
        "described": [],
        "pieces": [],
    }
    found.update(overrides)
    return found


def _said(ctx, monkeypatch, found):
    """What 'defects' says of the sound part when the wrapper answers 'found'."""
    from partcad.qual.topology.defects import DefectsTest

    async def answer(self, ctx, envelope, min_length):
        return found

    monkeypatch.setattr(DefectsTest, "_find", answer)
    result = _defects(ctx, "sound")
    assert result.status == report.WARNED
    return result.findings[0]["text"]


def test_one_sliver_that_could_not_be_drawn_is_not_all_of_it(ctx, monkeypatch):
    # What two LEGO parts said in CI: one edge in two thousand, drawn as
    # nothing, and then called the whole part.
    text = _said(ctx, monkeypatch, _found(defective_edges=1, slivers=1))
    assert "1 of its 2000 edges is defective" in text
    assert "all of it" not in text
    assert "none of them could be drawn" in text


def test_every_piece_defective_is_all_of_it(ctx, monkeypatch):
    text = _said(
        ctx,
        monkeypatch,
        _found(defective_faces=100, defective_edges=2000, slivers=2100, whole_faces=True, whole_edges=True),
    )
    assert "that is all of it, so there is nothing in particular to point at" in text


def test_every_face_defective_is_said_beside_the_edges_drawn(ctx, monkeypatch):
    text = _said(
        ctx,
        monkeypatch,
        _found(defective_faces=100, defective_edges=3, slivers=103, whole_faces=True, pieces=[{"kind": "edge"}]),
    )
    assert "every face is, which is all of it and is not drawn" in text
    assert "nothing in particular" not in text
