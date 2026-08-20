#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The parameter model the import dialog renders and reads back."""

import pytest
from partcad_freecad import params

CONFIG = {
    "name": "cube",
    "type": "cadquery",
    "parameters": {
        "width": {"type": "float", "default": 10.0},
        "count": {"type": "int", "default": 3},
        "label": {"type": "string", "default": "front"},
        "hollow": {"type": "bool", "default": False},
        "finish": {"type": "string", "default": "raw", "enum": ["raw", "anodized"]},
        "offsets": {"type": "array", "default": [1, 2]},
    },
}


def test_parameters_keep_their_declaration_order():
    specs = params.parse_parameters(CONFIG)

    assert [spec.name for spec in specs] == ["width", "count", "label", "hollow", "finish", "offsets"]


def test_an_undeclared_type_defaults_to_float():
    spec = params.parse_parameters({"parameters": {"height": {"default": 4}}})[0]

    assert spec.type == params.TYPE_FLOAT


def test_a_short_form_parameter_infers_its_type():
    specs = params.parse_parameters({"parameters": {"h": 10.0, "n": 3, "on": True, "s": "x", "a": [1]}})

    assert [spec.type for spec in specs] == [
        params.TYPE_FLOAT,
        params.TYPE_INT,
        params.TYPE_BOOL,
        params.TYPE_STRING,
        params.TYPE_ARRAY,
    ]


def test_an_object_without_parameters_yields_nothing():
    assert params.parse_parameters({"type": "step"}) == []
    assert params.parse_parameters({"parameters": None}) == []
    assert params.parse_parameters(None) == []


def test_enum_is_reported():
    finish = params.parse_parameters(CONFIG)[4]

    assert finish.is_enum
    assert finish.enum == ["raw", "anodized"]


@pytest.mark.parametrize(
    "type_name, raw, expected",
    [
        (params.TYPE_FLOAT, "2.5", 2.5),
        (params.TYPE_FLOAT, "2,5", 2.5),  # a decimal comma, as typed on many locales
        (params.TYPE_FLOAT, 3, 3.0),
        (params.TYPE_INT, "7", 7),
        (params.TYPE_INT, 7, 7),
        (params.TYPE_BOOL, "true", True),
        (params.TYPE_BOOL, "False", False),
        (params.TYPE_BOOL, True, True),
        (params.TYPE_STRING, 12, "12"),
        (params.TYPE_ARRAY, "[1, 2]", [1, 2]),
        (params.TYPE_ARRAY, "a, b", ["a", "b"]),
        (params.TYPE_ARRAY, "", []),
        (params.TYPE_ARRAY, [1], [1]),
    ],
)
def test_values_are_coerced_to_the_declared_type(type_name, raw, expected):
    assert params.ParamSpec("p", type_name).coerce(raw) == expected


def test_a_value_outside_a_declared_range_is_rejected():
    # A spin box clamps an int on its own, but a float goes through a line edit
    # whose validator lets an out-of-range value be typed, so the bound has to
    # hold here or it holds for one type only.
    spec = params.ParamSpec("width", params.TYPE_FLOAT, 5.0, min=1.0, max=10.0)

    assert spec.coerce("10") == 10.0
    with pytest.raises(ValueError, match="above the maximum"):
        spec.coerce("10.1")
    with pytest.raises(ValueError, match="below the minimum"):
        spec.coerce("0.9")


def test_a_parameter_without_a_range_accepts_anything_of_its_type():
    assert params.ParamSpec("width", params.TYPE_FLOAT).coerce("-1e6") == -1e6


def test_a_fractional_bound_on_an_int_is_not_truncated():
    spec = params.ParamSpec("count", params.TYPE_INT, 2, min=1.5)

    assert spec.coerce("2") == 2
    with pytest.raises(ValueError, match="below the minimum"):
        spec.coerce("1")


def test_bounds_do_not_apply_to_non_numeric_parameters():
    spec = params.ParamSpec("label", params.TYPE_STRING, "a", min=1, max=2)

    assert spec.coerce("zzz") == "zzz"


def test_a_bad_value_names_the_parameter():
    with pytest.raises(ValueError, match="width"):
        params.ParamSpec("width", params.TYPE_FLOAT).coerce("wide")


def test_a_bad_boolean_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError, match="expected a boolean"):
        params.ParamSpec("hollow", params.TYPE_BOOL).coerce("maybe")


def test_floats_are_formatted_as_floats():
    assert params.format_value(params.TYPE_FLOAT, 10) == "10.0"
    assert params.format_value(params.TYPE_FLOAT, 2.5) == "2.5"
    assert params.format_value(params.TYPE_FLOAT, None) == "0.0"


def test_other_defaults_are_formatted_for_a_control():
    assert params.format_value(params.TYPE_BOOL, True) == "true"
    assert params.format_value(params.TYPE_ARRAY, [1, 2]) == "[1, 2]"
    assert params.format_value(params.TYPE_STRING, None) == ""


def test_collect_coerces_every_control_value():
    specs = params.parse_parameters(CONFIG)

    values = params.collect(
        specs,
        {
            "width": "12,5",
            "count": 4,
            "label": "back",
            "hollow": True,
            "finish": "anodized",
            "offsets": "[3]",
        },
    )

    assert values == {
        "width": 12.5,
        "count": 4,
        "label": "back",
        "hollow": True,
        "finish": "anodized",
        "offsets": [3],
    }


def test_collect_skips_parameters_no_control_reported():
    specs = params.parse_parameters(CONFIG)

    assert params.collect(specs, {"count": 1}) == {"count": 1}


def test_instance_suffix_matches_partcads_own_naming():
    assert params.instance_suffix({"width": 20.0, "height": 5}) == ";height=5,width=20.0"
    assert params.instance_suffix({}) == ""
