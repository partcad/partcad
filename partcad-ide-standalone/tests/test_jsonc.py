#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json

import pytest

import jsonc
from conftest import REPO_ROOT


def test_line_comments_are_dropped():
    assert jsonc.loads('{\n  // a comment\n  "a": 1 // and another\n}') == {"a": 1}


def test_block_comments_are_dropped():
    assert jsonc.loads('{/* which */ "a": /* go */ 1 /* anywhere */}') == {"a": 1}


def test_a_block_comment_separates_the_tokens_around_it():
    # Removing it outright would turn this into the number 12 and read back a
    # value the file never stated.
    with pytest.raises(json.JSONDecodeError):
        jsonc.loads('{"a": 1/* between */2}')


def test_an_unterminated_block_comment_is_an_error():
    with pytest.raises(ValueError):
        jsonc.loads('{"a": 1 /* and the rest of the file')


def test_trailing_commas_are_dropped():
    assert jsonc.loads('{"a": [1, 2, ], "b": {"c": 3,},}') == {"a": [1, 2], "b": {"c": 3}}


def test_comments_inside_strings_are_kept():
    # The reason for parsing rather than deleting with a regular expression: a
    # URL in a value has two slashes in it and is not a comment.
    assert jsonc.loads('{"a": "https://partcad.org/ // not a comment"}') == {
        "a": "https://partcad.org/ // not a comment"
    }


def test_escaped_quotes_do_not_end_a_string():
    assert jsonc.loads(r'{"a": "say \"//\"", "b": 1}') == {"a": 'say "//"', "b": 1}


def test_the_repositorys_own_recommendations_parse():
    # The file this component reads to decide what the IDE ships with. It has
    # comments and a trailing comma today; both are what this parser is for.
    recommendations = jsonc.load(REPO_ROOT / ".vscode" / "extensions.json")["recommendations"]
    assert "redhat.vscode-yaml" in recommendations
