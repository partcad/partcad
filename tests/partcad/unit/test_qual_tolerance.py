#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'tolerance-surfaces' and 'tolerance-edges' on 'data/qual_tolerance', as the Topology tab asks them.

Each part reads the same STEP file, whose GD&T tolerances two faces of seven.
What differs is what the declaration says: nothing more, a general tolerance,
a general tolerance told not to count, bought, or not to be made.
"""

import asyncio

import pytest

import partcad as pc
from partcad.qual import highlight, report

PACKAGE = "tests/partcad/unit/data/qual_tolerance/partcad.yaml"


@pytest.fixture
def ctx():
    # Asked afresh: a verdict another run left in the cache says what it found
    # in that run's words, and a pass it left says nothing at all.
    config = pc.UserConfig()
    config.cache_bypass = True
    return pc.Context(PACKAGE, user_config=config)


def _topology(ctx, name, verify=True):
    part = ctx.get_part("//:%s" % name)
    results = asyncio.run(report.run_async(ctx, part, verify=verify, subtypes=["topology"]))
    return {result.name: result for result in results}


def test_a_topology_run_asks_only_the_topology_checks(ctx):
    results = _topology(ctx, "feature_by_feature", verify=False)
    assert list(results) == ["defects", "interference", "tolerance-surfaces", "tolerance-edges"]
    assert all(result.subtype == "topology" for result in results.values())


def test_a_part_that_is_not_made_or_is_bought_is_not_asked(ctx):
    bought = _topology(ctx, "bought", verify=False)
    assert bought["tolerance-surfaces"].status == report.NOT_APPLICABLE
    assert "bought" in bought["tolerance-surfaces"].findings[0]["text"]
    model = _topology(ctx, "model", verify=False)
    assert model["tolerance-edges"].status == report.NOT_APPLICABLE
    assert "manufacturable: false" in model["tolerance-edges"].findings[0]["text"]


def test_a_general_tolerance_covers_every_feature_without_measuring(ctx):
    results = _topology(ctx, "general")
    assert results["tolerance-surfaces"].status == report.PASSED
    assert "general tolerance of 0.1 mm" in results["tolerance-surfaces"].findings[0]["text"]
    assert results["tolerance-edges"].status == report.PASSED


def test_what_the_file_does_not_tolerance_fails_and_is_left_to_look_at(ctx):
    results = _topology(ctx, "feature_by_feature")
    faces = results["tolerance-surfaces"]
    assert faces.status == report.FAILED
    assert "5 of its 7 faces have no tolerance" in faces.findings[0]["text"]
    (artifact,) = faces.artifacts
    assert artifact["name"] == "feature_by_feature/tolerance-surfaces"
    assert artifact[highlight.FOCUS_KEY] == highlight.FOCUS
    # Registered, to be shown: the part, and what the finding is about.
    shown = ctx.get_assembly("//:feature_by_feature/tolerance-surfaces")
    assert shown is not None
    assert sorted(child.name for child in shown.children) == ["feature_by_feature", "focus"]
    faces_part = ctx.get_part("//:feature_by_feature/tolerance-surfaces/focus/faces")
    assert faces_part.config["properties"]["color"] == highlight.COLORS["face"]

    # A callout on each face, the largest first, where it is on the part.
    features = artifact[highlight.FEATURES_KEY]
    assert len(features) == 5
    assert all(feature["label"].startswith("face ") and "mm^2" in feature["label"] for feature in features)
    assert all(len(feature["at"]) == 3 for feature in features)

    edges = results["tolerance-edges"]
    assert edges.status == report.FAILED
    assert "13 of its 14 edges have no tolerance" in edges.findings[0]["text"]
    assert edges.artifacts[0]["title"] == "13 edges without a tolerance"
    assert len(edges.artifacts[0][highlight.FEATURES_KEY]) == highlight.MAX_FEATURES


def test_a_general_tolerance_told_not_to_count_and_small_faces_left_out(ctx):
    faces = _topology(ctx, "strict")["tolerance-surfaces"]
    assert faces.status == report.FAILED
    text = faces.findings[0]["text"]
    assert "1 of its 7 faces has no tolerance" in text
    assert "general: false" in text
    assert "4 smaller than 100 mm^2 not counted" in text


def test_a_part_that_tolerances_nothing_is_manufacturability_s_and_not_drawn(ctx):
    # Every face of it would be the finding, which is the part: nothing in
    # particular to point at (see 'partcad.qual.highlight.covers_all').
    results = _topology(ctx, "untoleranced")
    for name in ("tolerance-surfaces", "tolerance-edges"):
        assert results[name].status == report.NOT_APPLICABLE
        assert "manufacturability" in results[name].findings[0]["text"]
        assert results[name].artifacts == []


def test_a_finding_that_is_every_face_is_said_in_words_alone(ctx):
    faces = _topology(ctx, "told_off")["tolerance-surfaces"]
    assert faces.status == report.FAILED
    text = faces.findings[0]["text"]
    assert "none of its 6 faces has a tolerance" in text
    assert "general: false" in text
    assert "that is all of it" in text
    assert faces.artifacts == []
