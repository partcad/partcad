#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc update' writes one line of somebody's 'partcad.yaml', and only that line.

The file is a Jinja2 template the author wrote by hand, so what is being pinned
down is twofold: the edit lands where it belongs and every other byte stays as
it was, and where the edit would be a guess the file is left alone and the
reason comes back instead.
"""

import pytest

from partcad.dependency_pin import set_dependency_revision

SHA = "8c1517c6a65e0316910f5caff64291a56c7fa0c2"


def pin(tmp_path, text, dependency="pub", newline=""):
    path = tmp_path / "partcad.yaml"
    path.write_bytes(text.encode("utf-8"))
    reason = set_dependency_revision(str(path), dependency, SHA)
    return reason, path.read_bytes().decode("utf-8")


def test_a_revision_is_added_under_its_track(tmp_path):
    reason, after = pin(
        tmp_path,
        "name: //mine\n"
        "dependencies:\n"
        "  # The public index.\n"
        "  pub:\n"
        "    type: git\n"
        "    url: https://github.com/partcad/partcad-index.git\n"
        "    track: main  # the released state\n"
        "    onlyInRoot: true\n"
        "parts:\n"
        "  cube: {}\n",
    )
    assert reason is None
    assert after == (
        "name: //mine\n"
        "dependencies:\n"
        "  # The public index.\n"
        "  pub:\n"
        "    type: git\n"
        "    url: https://github.com/partcad/partcad-index.git\n"
        "    track: main  # the released state\n"
        "    revision: %s\n"
        "    onlyInRoot: true\n"
        "parts:\n"
        "  cube: {}\n" % SHA
    )


def test_an_existing_revision_is_replaced_and_its_comment_kept(tmp_path):
    reason, after = pin(
        tmp_path,
        "dependencies:\n"
        "    pub:\n"
        "        revision: 'abc1234'   # moved by pc update\n"
        "        track: main\n"
        "        url: https://example.com/pub.git\n",
    )
    assert reason is None
    assert after == (
        "dependencies:\n"
        "    pub:\n"
        "        revision: %s   # moved by pc update\n"
        "        track: main\n"
        "        url: https://example.com/pub.git\n" % SHA
    )


def test_only_the_named_dependency_is_touched(tmp_path):
    text = (
        "dependencies:\n"
        "  other:\n"
        "    url: https://example.com/other.git\n"
        "    track: main\n"
        "    revision: 1111111\n"
        "  pub:\n"
        "    url: https://example.com/pub.git\n"
        "    track: main\n"
        "    revision: 2222222\n"
        "  last:\n"
        "    path: ../last\n"
    )
    reason, after = pin(tmp_path, text)
    assert reason is None
    assert after == text.replace("2222222", SHA)


def test_windows_line_endings_survive(tmp_path):
    reason, after = pin(tmp_path, "dependencies:\r\n  pub:\r\n    url: u\r\n    track: main\r\nparts: {}\r\n")
    assert reason is None
    assert (
        after == "dependencies:\r\n  pub:\r\n    url: u\r\n    track: main\r\n    revision: %s\r\nparts: {}\r\n" % SHA
    )


def test_a_track_on_the_last_line_without_a_newline(tmp_path):
    reason, after = pin(tmp_path, "dependencies:\n  pub:\n    url: u\n    track: main")
    assert reason is None
    assert after == "dependencies:\n  pub:\n    url: u\n    track: main\n    revision: %s\n" % SHA


def test_quoted_keys_are_found(tmp_path):
    reason, after = pin(tmp_path, 'dependencies:\n  "pub":\n    url: u\n    "track": main\n')
    assert reason is None
    assert after == 'dependencies:\n  "pub":\n    url: u\n    "track": main\n    revision: %s\n' % SHA


def test_template_lines_around_it_are_kept(tmp_path):
    text = (
        "{% set index = 'https://github.com/partcad/partcad-index.git' %}\n"
        "dependencies:\n"
        "{% if partcad_version_at_least('0.8.201') %}\n"
        "  pub:\n"
        "    url: {{ index }}\n"
        "    track: main\n"
        "    revision: 1234567\n"
        "{% endif %}\n"
        "parts: {}\n"
    )
    reason, after = pin(tmp_path, text)
    assert reason is None
    assert after == text.replace("1234567", SHA)


def test_writing_what_is_there_already_changes_nothing(tmp_path):
    text = "dependencies:\n  pub:\n    track: main\n    revision: %s\n" % SHA
    reason, after = pin(tmp_path, text)
    assert reason is None
    assert after == text


@pytest.mark.parametrize(
    "text, why",
    [
        ("parts: {}\n", "no single top-level"),
        ("dependencies: {pub: {url: u, track: main}}\n", "not written in block style"),
        ("dependencies:\n  pub: {url: u, track: main}\n", "not written in block style"),
        ("dependencies:\n  other:\n    url: u\n    track: main\n", "not written out as an entry"),
        (
            "dependencies:\n{% if a %}\n  pub:\n    track: main\n{% else %}\n  pub:\n    track: devel\n{% endif %}\n",
            "declared 2 times",
        ),
        ("dependencies:\n  pub:\n    track: main\n    revision: '{{ pin }}'\n", "template expression"),
        ("dependencies:\n  pub:\n    url: u\n", "'track:' is not written out"),
        ("dependencies:\n  pub:\n    track: main\n    track: devel\n", "more than once"),
    ],
)
def test_what_would_be_a_guess_is_left_alone(tmp_path, text, why):
    reason, after = pin(tmp_path, text)
    assert reason is not None and why in reason
    assert after == text
