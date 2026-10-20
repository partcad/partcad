#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a command line says about parameters.

An override (`partcad_utils.parameters.parse_override`), and the values a
request assigns to the object it names (`assignments`, `assign`).
"""

import pytest

from partcad_utils.parameters import assign, assignments, format_assignment, parse_override
from partcad_utils.user_config import user_config


@pytest.mark.parametrize(
    "text, expected",
    [
        ("desk.length=60", ("desk", "length", "60")),
        ("//pub/furniture:desk.length=60", ("//pub/furniture:desk", "length", "60")),
        # The object's name may have dots of its own, anywhere.
        ("//pub/v1.2:bracket.v2.length=60", ("//pub/v1.2:bracket.v2", "length", "60")),
        ("//p:a.b.len=1.5", ("//p:a.b", "len", "1.5")),
        # And the value may hold anything, dots and '=' included.
        ("desk.label=a.b=c", ("desk", "label", "a.b=c")),
        ("desk.label=", ("desk", "label", "")),
        # An object named with parameters of its own.
        ("//p:desk;length=60.width=30", ("//p:desk;length=60", "width", "30")),
    ],
)
def test_an_override_names_an_object_a_parameter_and_a_value(text, expected):
    assert parse_override(text) == expected


@pytest.mark.parametrize("text", ["length=60", ".length=60", "desk.=60", "desk.length", "", " .x=1"])
def test_what_is_not_an_override_is_refused(text):
    with pytest.raises(ValueError):
        parse_override(text)


def test_a_configuration_section_answers_in():
    """'in' used to answer False whatever the section held."""
    user_config.parameter_config["//test:membership"] = {"a": 1}
    try:
        assert "//test:membership" in user_config.parameter_config
        assert "//test:absent" not in user_config.parameter_config
    finally:
        del user_config.parameter_config["//test:membership"]
    assert "//test:membership" not in user_config.parameter_config


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, {}),
        ([], {}),
        ({}, {}),
        # What 'pc -p' sends.
        (["length=10", "head=hex"], {"length": "10", "head": "hex"}),
        # And what the editor, the FreeCAD addon and an agent send, as it is.
        ({"length": 10, "flat": True}, {"length": 10, "flat": True}),
        # Only the first '=' separates; a value may hold '=', ',' and ':'.
        (
            ["label=a=b", "include=UP,DOWN", "medium=//pub/std:air"],
            {"label": "a=b", "include": "UP,DOWN", "medium": "//pub/std:air"},
        ),
        (["label="], {"label": ""}),
        # The last of two for one parameter wins, as the last '-p' should.
        (["length=10", "length=12"], {"length": "12"}),
    ],
)
def test_both_shapes_of_assignment_read_the_same(value, expected):
    assert assignments(value) == expected


@pytest.mark.parametrize("value", [["length"], ["=10"], "length=10", 10])
def test_what_assigns_nothing_is_refused(value):
    """Not passed over: 'pc info -p width' used to show the object at its default width."""
    with pytest.raises(ValueError):
        assignments(value)


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, "true"),
        (False, "false"),
        (10, "10"),
        (2.5, "2.5"),
        ("hex", "hex"),
        # A list is how a name spells one (see 'parse_parameterized_name').
        (["BEND_UP", "BEND_DOWN"], "BEND_UP,BEND_DOWN"),
    ],
)
def test_a_value_is_written_the_way_a_name_spells_it(value, expected):
    assert format_assignment(value) == expected


@pytest.mark.parametrize(
    "name, values, expected",
    [
        ("bolt", None, "bolt"),
        ("bolt", ["length=10"], "bolt;length=10"),
        ("bolt", {"length": 10, "flat": True}, "bolt;flat=true,length=10"),
        # One spelling for one instance, whichever way it was asked for.
        ("bolt;length=10", ["head=hex"], "bolt;head=hex,length=10"),
        # A value given here wins over the one the name carries: it is the outer.
        ("bolt;length=10", ["length=12"], "bolt;length=12"),
        # The package, and the walk, are the name's and stay as they were.
        ("//pub/std:bolt", ["length=10"], "//pub/std:bolt;length=10"),
        ("...:bolt", ["length=10"], "...:bolt;length=10"),
        ("panel", {"include": ["BEND_UP", "BEND_DOWN"]}, "panel;include=BEND_UP,BEND_DOWN"),
    ],
)
def test_assigned_values_are_written_into_the_name(name, values, expected):
    assert assign(name, values) == expected
