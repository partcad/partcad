#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'partcad_utils.comments': what a comment is, as every reader reads it and every writer makes it."""

import datetime
import subprocess

import pytest

from partcad_utils import comments


def test_a_date_is_utc_to_the_second_and_reads_as_one():
    moment = datetime.datetime(2026, 11, 19, 15, 31, 1, 999, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
    assert comments.date(moment) == "2026-11-19 14:31:01 UTC"
    assert comments.DATE_PATTERN.match(comments.date())
    # A naive moment is taken to be UTC already.
    assert comments.date(datetime.datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02 03:04:05 UTC"


@pytest.mark.parametrize(
    "ref, parsed",
    [
        ("face:12", ("face", 12)),
        (" edge:3 ", ("edge", 3)),
        ("face:0", None),
        ("Face:1", None),
        ("vertex:1", None),
        ("base", None),
        ("link#2", None),
        (None, None),
        (12, None),
    ],
)
def test_a_reference_to_a_face_or_an_edge_is_read_and_nothing_else_is_taken_for_one(ref, parsed):
    assert comments.parse_element_ref(ref) == parsed


def test_a_reference_to_a_face_or_an_edge_is_written_one_way():
    assert comments.element_ref("face", 12) == "face:12"
    assert comments.describe_ref("face:12") == "face 12"
    assert comments.describe_ref("arm:link#1") == "arm:link#1"
    assert comments.describe_ref(None) == "the whole object"
    with pytest.raises(ValueError):
        comments.element_ref("vertex", 1)
    with pytest.raises(ValueError):
        comments.element_ref("face", 0)


def test_threads_are_read_as_text_keeping_their_positions():
    declaration = {
        "comments": [
            [
                {
                    "ref": "face:1",
                    "name": "Ada",
                    # What a YAML reader makes of a date written without ' UTC'.
                    "date": datetime.datetime(2026, 11, 19, 14, 31, 1),
                    "text": "thin",
                    "attachments": ["a.png", None, 3],
                },
                "not a comment",
                {"name": "Charles", "date": "2026-11-19 15:00:00 UTC", "text": "fixed"},
            ],
            "not a thread",
            [{"name": "Grace", "date": "2026-11-20 09:00:00 UTC", "text": "whole"}],
        ]
    }
    threads = comments.threads(declaration)
    assert len(threads) == 3
    assert threads[0][0] == {
        "ref": "face:1",
        "name": "Ada",
        "date": "2026-11-19 14:31:01 UTC",
        "text": "thin",
        "attachments": ["a.png", "3"],
    }
    assert [entry["name"] for entry in threads[0]] == ["Ada", "Charles"]
    assert threads[1] == []
    assert comments.thread_ref(threads[0]) == "face:1"
    assert comments.thread_ref(threads[2]) is None
    assert comments.threads({"comments": None}) == []
    assert comments.threads("bolt: //pub/std:bolt") == []


def test_a_comment_is_made_with_who_when_and_what():
    entry = comments.entry(
        " Ada ", "Too *thin*.\n\n", ref="face:12", attachments=["photos\\crack.jpg"], when="2026-11-19 14:31:01 UTC"
    )
    assert list(entry) == ["ref", "name", "date", "text", "attachments"]
    assert entry == {
        "ref": "face:12",
        "name": "Ada",
        "date": "2026-11-19 14:31:01 UTC",
        "text": "Too *thin*.",
        "attachments": ["photos/crack.jpg"],
    }
    # About the object as a whole, and dated now.
    entry = comments.entry("Ada", "ok")
    assert "ref" not in entry and "attachments" not in entry
    assert comments.DATE_PATTERN.match(entry["date"])


@pytest.mark.parametrize(
    "name, text, kwargs",
    [
        ("", "text", {}),
        (None, "text", {}),
        ("Ada", "  ", {}),
        ("Ada", "text", {"when": "2026-11-19T14:31:01Z"}),
        ("Ada", "text", {"attachments": [""]}),
        ("Ada", "text", {"ref": 12}),
    ],
)
def test_what_is_not_a_comment_is_refused(name, text, kwargs):
    with pytest.raises(ValueError):
        comments.entry(name, text, **kwargs)


def test_a_comment_is_signed_with_the_name_git_gives_here(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Ada Lovelace"], cwd=tmp_path, check=True)
    assert comments.author(str(tmp_path)) == "Ada Lovelace"
