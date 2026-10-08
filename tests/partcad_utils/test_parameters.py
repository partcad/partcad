#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an override written on a command line says: `partcad_utils.parameters.parse_override`."""

import pytest

from partcad_utils.parameters import parse_override
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
