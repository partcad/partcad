#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the interference check leaves behind for two parts that overlap.

An assembly of the two, placed where the checked assembly places them, and a
sub-assembly 'interference' of the volumes they share, registered in memory
under names worked out from what they are. The subject is the package of
'test_requirements.py': 'pair' places 'plate' twice, as 'lower' and 'upper'.
Nothing is built: the volumes are files whose bytes nothing here reads.
"""

import asyncio
import os

import pytest

import partcad as pc
from partcad.assembly import placed_leaves
from partcad.geom import Location
from partcad.test import interference_artifact

PACKAGE = "tests/partcad/unit/data/requirements/partcad.yaml"

UPPER = [[0.0, 0.0, 20.0], [0.0, 0.0, 1.0], 0.0]


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    context = pc.Context(PACKAGE)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path))
    return context


def _overlap(a="lower", b="upper", brep=b"the BREP of what they share"):
    return {
        "a": a,
        "b": b,
        "volume": 1.5,
        "solids": [{"brep": brep}],
        "members": {
            "a": {"object": "//:plate", "location": Location().as_packed()},
            "b": {"object": "//:plate", "location": UPPER},
        },
    }


def test_each_part_is_named_and_placed_as_the_wrapper_names_and_places_it():
    tree = {
        "name": "//pkg:robot",
        "location": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], 0.0],
        "assembly": [
            {
                "name": "//pkg:arm",
                "label": "arm",
                "location": [[10.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0],
                "assembly": [
                    {"name": "//pkg:link", "label": "link", "brep": "AAAA", "location": [[1.0, 0.0, 0.0], [0, 0, 1], 0]}
                ],
            },
            {"name": "//pkg:base", "brep": "AAAA"},
        ],
    }
    leaves = placed_leaves(tree)
    assert sorted(leaves) == ["//pkg:base", "arm/link"]
    assert leaves["arm/link"]["object"] == "//pkg:link"
    # The link's own offset, turned with the arm, moved with the arm, then the root.
    position = leaves["arm/link"]["location"][0]
    assert position == pytest.approx([10.0, 1.0, 1.0])
    assert leaves["//pkg:base"]["location"][0] == pytest.approx([0.0, 0.0, 1.0])


def test_an_overlap_leaves_the_two_parts_and_what_they_share(ctx, tmp_path):
    pair = ctx.get_assembly("//:pair")
    artifact = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap()))

    assert artifact["name"] == "pair/interference/lower+upper"
    assert artifact["package"] == pair.project_name and artifact["kind"] == "assembly"
    assert artifact["title"] == "'lower' and 'upper'"

    # Found by name, as anything that shows an object asks for one.
    shown = ctx.get_assembly("//:pair/interference/lower+upper")
    assert shown is not None
    assert [child.name for child in shown.children] == ["lower", "upper", "interference"]
    assert [child.item.name for child in shown.children[:2]] == ["plate", "plate"]
    assert shown.children[1].location.as_packed()[0] == pytest.approx(UPPER[0])

    shared = shown.children[2].item
    assert [child.name for child in shared.children] == ["volume-1"]
    volume = shared.children[0].item
    assert volume.name == "pair/interference/lower+upper/interference/volume-1"
    assert volume.config["type"] == "brep"
    path = volume.config["path"]
    assert os.path.dirname(path) == os.path.join(str(tmp_path), "interference")
    with open(path, "rb") as stream:
        assert stream.read() == b"the BREP of what they share"


def test_the_same_overlap_is_left_under_the_same_names_and_in_the_same_file(ctx):
    pair = ctx.get_assembly("//:pair")
    first = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap()))
    again = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap()))
    assert first == again


def test_an_overlap_that_changed_replaces_what_was_left_before(ctx):
    pair = ctx.get_assembly("//:pair")
    asyncio.run(interference_artifact.make_async(ctx, pair, _overlap()))
    changed = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap(brep=b"a different overlap")))
    volume = ctx.get_part("//:pair/interference/lower+upper/interference/volume-1")
    assert volume.config["path"] == changed["recipe"]["volumes"][0]


def test_two_parts_of_one_name_are_told_apart_by_where_they_are(ctx):
    pair = ctx.get_assembly("//:pair")
    artifact = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap(a="tub/plate", b="lid/plate")))
    shown = ctx.get_assembly("//:" + artifact["name"])
    assert [child.name for child in shown.children[:2]] == ["tub.plate", "lid.plate"]


def test_what_cannot_be_shown_is_not_offered(ctx):
    pair = ctx.get_assembly("//:pair")
    nothing_shared = _overlap()
    nothing_shared["solids"] = []
    assert asyncio.run(interference_artifact.make_async(ctx, pair, nothing_shared)) is None

    artifact = asyncio.run(interference_artifact.make_async(ctx, pair, _overlap()))
    os.unlink(artifact["recipe"]["volumes"][0])
    assert asyncio.run(interference_artifact.restore_async(ctx, artifact)) is False
