#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'comment.list', 'comment.add' and 'comment.locate': the comments of a package and its objects, over the wire.

Against a real context of a package written to a temporary directory. Where a
thread about a face or an edge is, and which face or edge a point is on, are
worked out in a sandbox ('element_refs' among the wrappers, tested in
'tests/partcad/unit/test_element_refs.py'); here that half is stood in for, and
what is pinned is the method -- what it lists, writes and refuses.
"""

import pytest
import yaml

import partcad as pc
from partcad import measure
from partcad.part import Part
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry

ADA = {"name": "Ada Lovelace", "date": "2026-11-19 14:31:01 UTC"}


@pytest.fixture
def package(tmp_path, monkeypatch):
    config = {
        "name": "//shop",
        "comments": [[{**ADA, "text": "Prices are in euros."}]],
        "parts": {
            "bracket": {
                "type": "basic",
                "cylinder": {"radius": 4, "height": 10},
                "comments": [
                    [{**ADA, "ref": "face:3", "text": "Too thin."}],
                    [{**ADA, "text": "Whole part."}],
                ],
            },
            "bolt": "//pub/std:bolt",
        },
        "colors": {"red": {"display": "#C91A09"}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (tmp_path / "photos").mkdir()

    async def get_wrapped(self, ctx):
        return {"brep": b"stand-in"}

    monkeypatch.setattr(Part, "get_wrapped", get_wrapped)
    return tmp_path


def _session(path):
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(path))
    return session


def test_they_are_methods_of_the_daemon():
    registry = build_registry()
    assert registry["comment.list"].__wrapped__ is operations.comment_list
    assert registry["comment.add"].__wrapped__ is operations.comment_add
    assert registry["comment.locate"].__wrapped__ is operations.comment_locate


def test_an_objects_threads_are_listed_with_where_they_are_written(package):
    answer = operations.comment_list(_session(package), {"package": "//shop", "object": "bracket"})

    (found,) = answer["objects"].values()
    assert found["object"] == "//shop:bracket"
    assert found["kind"] == "part"
    assert found["writable"] is True
    assert found["config"].endswith("partcad.yaml")
    assert [(t["index"], t["ref"], t["about"]) for t in found["threads"]] == [
        (0, "face:3", "face 3"),
        (1, None, "the whole object"),
    ]
    assert found["threads"][0]["comments"][0]["text"] == "Too thin."
    # Not asked where: nothing was built for it.
    assert "at" not in found["threads"][0]


def test_the_package_s_own_threads_are_listed_when_no_object_is_named(package):
    answer = operations.comment_list(_session(package), {"package": "//shop"})

    (found,) = answer["objects"].values()
    assert found["kind"] is None
    assert found["threads"][0]["comments"][0]["text"] == "Prices are in euros."


def test_the_3d_view_asks_about_several_and_where_the_faces_are(package, monkeypatch):
    asked = []

    async def anchors(ctx, shape, refs, cacheable=True):
        asked.append(refs)
        return {"face:3": [1.0, 2.0, 3.0]}

    monkeypatch.setattr(measure, "element_anchors", anchors)
    answer = operations.comment_list(
        _session(package),
        {"package": "//shop", "objects": ["//shop:bracket", "//shop:nothing"], "anchors": True},
    )

    assert asked == [["face:3"]]
    bracket = answer["objects"]["//shop:bracket"]
    assert bracket["threads"][0]["at"] == [1.0, 2.0, 3.0]
    assert "at" not in bracket["threads"][1]
    # One that is not found says so, and does not fail the rest.
    assert "not found" in answer["objects"]["//shop:nothing"]["error"]


def test_a_comment_is_written_and_read_back(package):
    session = _session(package)
    answer = operations.comment_add(
        session,
        {
            "package": "//shop",
            "object": "bracket",
            "ref": "face:3",
            "thread": 0,
            "name": "Charles Babbage",
            "text": "Thickened to 2 mm.",
            "attachments": [str(package / "photos" / "after.jpg"), "notes.md"],
        },
    )
    assert answer["thread"] == 0
    assert answer["comment"]["attachments"] == ["photos/after.jpg", "notes.md"]

    listed = operations.comment_list(session, {"package": "//shop", "object": "bracket"})
    (found,) = listed["objects"].values()
    assert [c["name"] for c in found["threads"][0]["comments"]] == ["Ada Lovelace", "Charles Babbage"]


def test_a_short_form_and_a_colour_are_commented_on_too(package):
    session = _session(package)
    operations.comment_add(session, {"package": "//shop", "object": "bolt", "name": "Ada", "text": "Which grade?"})
    operations.comment_add(
        session, {"package": "//shop", "object": "red", "kind": "color", "name": "Ada", "text": "Too dark."}
    )
    written = yaml.safe_load((package / "partcad.yaml").read_text())
    assert written["parts"]["bolt"]["source"] == "//pub/std:bolt"
    assert written["parts"]["bolt"]["comments"][0][0]["text"] == "Which grade?"
    assert written["colors"]["red"]["comments"][0][0]["text"] == "Too dark."


@pytest.mark.parametrize(
    "params, refusal",
    [
        ({"object": "bracket", "text": "unsigned"}, "who wrote it"),
        ({"object": "bracket", "name": "Ada", "text": ""}, "empty"),
        ({"object": "bracket", "name": "Ada", "text": "x", "thread": 7}, "no thread 7"),
        ({"object": "bracket", "name": "Ada", "text": "x", "thread": True}, "index of a thread"),
        ({"object": "bracket", "name": "Ada", "text": "x", "attachments": ["/elsewhere/x.png"]}, "not inside"),
        ({"object": "bracket", "name": "Ada", "text": "x", "attachments": ["../x.png"]}, "not inside"),
        ({"object": "bracket", "name": "Ada", "text": "x", "date": "yesterday"}, "UTC"),
        ({"object": "nothing", "name": "Ada", "text": "x"}, "not found"),
    ],
)
def test_what_cannot_be_written_is_refused_with_nothing_written(package, params, refusal):
    before = (package / "partcad.yaml").read_text()
    with pytest.raises(JsonRpcError) as refused:
        operations.comment_add(_session(package), {"package": "//shop", **params})
    assert refusal in str(refused.value)
    assert (package / "partcad.yaml").read_text() == before


def test_a_click_is_located_on_a_part(package, monkeypatch):
    asked = []

    async def locate(ctx, shape, point, tolerance=0.0):
        asked.append((point, tolerance))
        return {"ref": "edge:4", "element": "edge", "index": 4, "at": [0, 0, 10], "distance": 0.1}

    monkeypatch.setattr(measure, "locate_element", locate)
    found = operations.comment_locate(
        _session(package), {"package": "//shop", "object": "bracket", "point": [0, 0.1, 10], "tolerance": 0.5}
    )
    assert asked == [([0, 0.1, 10], 0.5)]
    assert (found["object"], found["kind"], found["ref"], found["about"]) == (
        "//shop:bracket",
        "part",
        "edge:4",
        "edge 4",
    )


@pytest.mark.parametrize(
    "params, refusal",
    [
        ({"object": "bracket", "point": [0, 0]}, "'point'"),
        ({"object": "bracket", "point": [0, 0, "x"]}, "'point'"),
        ({"object": "bracket", "point": [0, 0, 0], "tolerance": "near"}, "'tolerance'"),
        ({"object": "red", "kind": "color", "point": [0, 0, 0]}, "neither"),
    ],
)
def test_a_click_that_cannot_be_located_is_refused(package, params, refusal):
    with pytest.raises(JsonRpcError) as refused:
        operations.comment_locate(_session(package), {"package": "//shop", **params})
    assert refusal in str(refused.value)
