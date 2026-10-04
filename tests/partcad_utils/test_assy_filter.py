#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the link mask in ``partcad_utils.assy_filter``.

The mask is read by three things that must agree -- ``pc filter``, a filtered
render, and the panel beside the IDE's 2D and Draft tabs -- so what is pinned
here is the semantics rather than any one caller's use of it: which links a mask
keeps, what naming a link with and without children means, and the two ways an
argument becomes a mask (a file, or the text itself).
"""

import json

import pytest

from partcad_utils import assy_filter
from partcad_utils.assy_filter import Filter, FilterError

# ---- reading a mask --------------------------------------------------------


@pytest.mark.parametrize("data", [None, True, {}, [], Filter().children])
def test_nothing_under_a_link_keeps_everything_under_it(data):
    mask = assy_filter.parse(data)
    assert mask.keeps_all
    # A mask that keeps everything answers for every name, so a walk below it
    # costs nothing.
    assert mask.select("anything") is mask


def test_a_mapping_names_the_links_to_keep():
    mask = assy_filter.parse({"head": {"half": None}, "bolt": None})
    assert not mask.keeps_all
    assert mask.names() == ["head", "bolt"]
    assert mask.select("bolt").keeps_all
    assert mask.select("head").names() == ["half"]
    assert mask.select("bone") is None


def test_a_list_is_a_mapping_of_names_with_nothing_under_them():
    mask = assy_filter.parse(["bone1", "bone2"])
    assert mask.names() == ["bone1", "bone2"]
    assert mask.select("bone1").keeps_all


def test_a_list_item_may_carry_a_sub_mask():
    mask = assy_filter.parse([{"head": ["half"]}, "bolt"])
    assert mask.names() == ["head", "bolt"]
    assert mask.select("head").names() == ["half"]


def test_a_number_is_read_as_the_name_it_is_written_as():
    # A YAML key that looks like a number parses as one, and a link may well be
    # called '1'. Refusing it would refuse a legal ASSY file.
    mask = assy_filter.parse({1: None})
    assert mask.select("1").keeps_all


@pytest.mark.parametrize("data", ["bone1", 7, 1.5, b"x"])
def test_anything_that_is_not_a_tree_of_names_is_refused(data):
    with pytest.raises(FilterError):
        assy_filter.parse(data)


def test_a_bare_word_says_how_to_write_it_properly():
    # The shape an unreadable *filename* parses to, which is why it is refused
    # rather than read as one link: a typo would otherwise render nothing.
    with pytest.raises(FilterError, match="bone1"):
        assy_filter.parse("bone1")


def test_a_malformed_value_names_where_it_was_found():
    with pytest.raises(FilterError, match="'head'"):
        assy_filter.parse({"head": 3})


def test_the_three_rules_a_link_is_named_by():
    # 'name:' wins; then what the node places; then where it is written.
    assert assy_filter.link_name({"name": "head", "part": "cube"}, 0) == "head"
    assert assy_filter.link_name({"part": "cube"}, 0) == "cube"
    assert assy_filter.link_name({"assembly": "frame"}, 0) == "frame"
    assert assy_filter.link_name({"links": []}, 0) == "link#1"
    assert assy_filter.link_name({"links": []}, 4) == "link#5"
    # Out of context there is no position to name it by, and saying so is better
    # than inventing one: a node that is a whole file is in no list.
    assert assy_filter.link_name({"links": []}) is None
    assert assy_filter.synthetic_link_name(0) == "link#1"


# ---- resolving the argument ------------------------------------------------


def test_a_file_is_read_as_yaml(tmp_path):
    path = tmp_path / "f.yaml"
    path.write_text("head:\n  half:\n", encoding="utf-8")
    data, source = assy_filter.resolve_spec(str(path))
    assert data == {"head": {"half": None}}
    assert source == str(path)


def test_a_file_is_read_as_json_too(tmp_path):
    # One parser for both: YAML is a superset of JSON, so a '.json' filter needs
    # no second code path.
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"head": {"half": None}}), encoding="utf-8")
    data, _ = assy_filter.resolve_spec(str(path))
    assert data == {"head": {"half": None}}


def test_a_file_with_a_byte_order_mark_is_read(tmp_path):
    path = tmp_path / "f.yaml"
    path.write_bytes("﻿head:\n".encode("utf-8"))
    data, _ = assy_filter.resolve_spec(str(path))
    assert data == {"head": None}


def test_the_text_itself_is_read_when_there_is_no_such_file():
    data, source = assy_filter.resolve_spec("{head: {half: null}}")
    assert data == {"head": {"half": None}}
    assert "command line" in source


def test_a_missing_file_says_both_things_that_went_wrong():
    # A mistyped filename and a malformed filter are fixed in different places,
    # so the message says which of the two happened.
    with pytest.raises(FilterError, match="nosuch.yaml") as caught:
        assy_filter.resolve_spec("nosuch.yaml")
    assert "mapping or list" in str(caught.value)


def test_a_file_that_does_not_parse_is_reported_as_the_file(tmp_path):
    path = tmp_path / "f.yaml"
    path.write_text("head: [unclosed\n", encoding="utf-8")
    with pytest.raises(FilterError, match=str(path)):
        assy_filter.resolve_spec(str(path))


def test_an_empty_argument_is_refused():
    with pytest.raises(FilterError):
        assy_filter.resolve_spec("   ")


def test_of_reads_the_data_a_request_carries():
    assert assy_filter.of(None) is None
    assert assy_filter.of({"a": None}).names() == ["a"]
    assert assy_filter.of("{a: null}").names() == ["a"]
    mask = Filter({"a": Filter()})
    assert assy_filter.of(mask) is mask


def test_of_never_reads_the_text_as_a_path(tmp_path):
    # The daemon is not where the user's files are, so a filter that arrives as
    # text is an expression and nothing else.
    path = tmp_path / "f.yaml"
    path.write_text("head:\n", encoding="utf-8")
    with pytest.raises(FilterError):
        assy_filter.of(str(path))


# ---- filtering a document --------------------------------------------------


def document():
    return {
        "links": [
            {"part": "cube", "name": "base"},
            {
                "name": "tower",
                "links": [
                    {"part": "cube", "name": "lower"},
                    {"part": "cube", "name": "upper"},
                ],
            },
            {"part": "pin", "name": "spike"},
        ]
    }


def names(links):
    return [assy_filter.link_name(node, index) for index, node in enumerate(links)]


def test_a_named_link_without_children_keeps_everything_inside_it():
    doc = document()
    assert assy_filter.filter_document(doc, assy_filter.parse({"tower": None})) == []
    assert names(doc["links"]) == ["tower"]
    assert names(doc["links"][0]["links"]) == ["lower", "upper"]


def test_a_named_link_with_children_keeps_only_those():
    doc = document()
    assert assy_filter.filter_document(doc, assy_filter.parse({"tower": {"upper": None}})) == []
    assert names(doc["links"]) == ["tower"]
    assert names(doc["links"][0]["links"]) == ["upper"]


def test_the_links_not_named_are_dropped():
    doc = document()
    assy_filter.filter_document(doc, assy_filter.parse(["base", "spike"]))
    assert names(doc["links"]) == ["base", "spike"]


def test_a_node_is_named_after_what_it_places_when_it_has_no_name_of_its_own():
    doc = {"links": [{"part": "cube"}, {"assembly": "frame"}]}
    assy_filter.filter_document(doc, assy_filter.parse(["cube"]))
    assert names(doc["links"]) == ["cube"]


def test_a_mask_that_keeps_everything_changes_nothing():
    doc = document()
    before = json.dumps(doc, sort_keys=True)
    assert assy_filter.filter_document(doc, assy_filter.KEEP_ALL) == []
    assert json.dumps(doc, sort_keys=True) == before


def test_a_container_with_no_name_is_addressed_by_its_position():
    # Every link has a name, and a 'links:' that gave itself none is called
    # after where it is written -- one-based, so the second entry is 'link#2'.
    doc = {
        "links": [
            {"part": "cube", "name": "base"},
            {"links": [{"part": "cube", "name": "inner"}, {"part": "pin", "name": "dropped"}]},
        ]
    }
    assert assy_filter.filter_document(doc, assy_filter.parse({"link#2": {"inner": None}})) == []
    # Written down as it is kept: it was the second link of two and is now the
    # only one, so a position would have renamed it -- and anything that named
    # it, a 'connect:' included, would then point at nothing.
    assert doc["links"][0]["name"] == "link#2"
    assert names(doc["links"]) == ["link#2"]
    assert names(doc["links"][0]["links"]) == ["inner"]


def test_a_positional_name_is_the_position_in_its_own_list():
    doc = {
        "links": [
            {"links": [{"part": "cube", "name": "a"}]},
            {"links": [{"part": "cube", "name": "b"}]},
        ]
    }
    # Each list positions its own links, so the inner ones are both 'link#1'
    # while the outer two are 'link#1' and 'link#2'.
    assert assy_filter.filter_document(doc, assy_filter.parse({"link#2": None})) == []
    assert names(doc["links"]) == ["link#2"]
    assert names(doc["links"][0]["links"]) == ["b"]
    # The inner list is untouched, so its own 'link#1' is still 'link#1'.
    assert assy_filter.link_name(doc["links"][0]["links"][0], 0) == "b"


def test_a_container_with_no_name_is_dropped_like_any_other_link():
    doc = {"links": [{"part": "cube", "name": "base"}, {"links": [{"part": "pin", "name": "dropped"}]}]}
    assy_filter.filter_document(doc, assy_filter.parse(["base"]))
    assert names(doc["links"]) == ["base"]


def test_a_name_that_is_no_link_is_reported():
    doc = document()
    problems = assy_filter.filter_document(doc, assy_filter.parse(["base", "nosuch"]))
    assert len(problems) == 1
    assert "nosuch" in problems[0]
    # Reported, not fatal: the links that were named are still kept.
    assert names(doc["links"]) == ["base"]


def test_selecting_inside_a_part_is_reported_and_the_link_kept_whole():
    doc = document()
    problems = assy_filter.filter_document(doc, assy_filter.parse({"base": {"anything": None}}))
    assert len(problems) == 1
    assert "'base'" in problems[0]
    assert names(doc["links"]) == ["base"]


def test_a_file_with_no_links_has_nothing_to_select_from():
    doc = {"part": "cube"}
    problems = assy_filter.filter_document(doc, assy_filter.parse(["cube"]))
    assert len(problems) == 1
    assert "no 'links:'" in problems[0]


def test_a_file_with_no_links_and_no_selection_is_left_alone():
    doc = {"part": "cube"}
    assert assy_filter.filter_document(doc, assy_filter.KEEP_ALL) == []
    assert doc == {"part": "cube"}


# ---- what identifies a mask ------------------------------------------------


def test_a_mask_round_trips_to_the_data_it_was_read_from():
    assert assy_filter.parse(None).data() is None
    assert assy_filter.parse({"head": {"half": None}}).data() == {"head": {"half": None}}
    # A list is read as names, so it comes back as the mapping it means.
    assert assy_filter.parse(["a", "b"]).data() == {"a": None, "b": None}


def test_two_spellings_of_one_selection_are_one_key():
    # What the key is for: building the subset an output file is of at most once
    # per selection, however many file types ask for it.
    assert assy_filter.parse(["a", "b"]).key() == assy_filter.parse(["b", "a"]).key()
    assert assy_filter.parse({"a": None}).key() == assy_filter.parse({"a": {}}).key()
    assert assy_filter.parse(["a"]).key() != assy_filter.parse(["b"]).key()
    assert assy_filter.parse({"a": ["b"]}).key() != assy_filter.parse({"a": None}).key()
    assert assy_filter.KEEP_ALL.key() == "*"
