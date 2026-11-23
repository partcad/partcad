#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The schema of a routed part (issue #975, task 3.1).

A routed part's profile is a round section ('diameter', hollow with
'innerDiameter') or a sketch: exactly one of the two. 'length' and
'minBendRadius' describe the real cable and are checked by 'pc qual test'.
That 'innerDiameter' is smaller than 'diameter' the schema cannot say (draft-07
compares no two values); the part checks it (see 'test_part_routed_config.py').
"""

import jsonschema
import pytest

from partcad.lint.all import get_partcad_schema


def _package(**part):
    return {"parts": {"tube": dict({"type": "routed"}, **part)}}


@pytest.mark.parametrize(
    "part",
    [
        {"diameter": 6},
        {"diameter": 6, "innerDiameter": 4},
        {"sketch": "flat-cable-section"},
        {"diameter": 6, "innerDiameter": 4, "length": 300, "minBendRadius": 15},
        {"sketch": "flat-cable-section", "length": 1000},
        {"diameter": 6, "ports": {"gland": [[0, 0, -12], [0, 0, 1], 0]}},
    ],
)
def test_a_routed_part_with_one_profile_is_valid(part):
    jsonschema.validate(_package(**part), get_partcad_schema())


@pytest.mark.parametrize(
    "part",
    [
        {},
        {"diameter": 6, "sketch": "flat-cable-section"},
        {"length": 300},
        {"sketch": "flat-cable-section", "innerDiameter": 4},
        {"innerDiameter": 4},
    ],
    ids=["neither", "both", "only-length", "bore-on-a-sketch", "bore-only"],
)
def test_a_routed_part_without_exactly_one_profile_is_refused(part):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_package(**part), get_partcad_schema())


@pytest.mark.parametrize("field", ["diameter", "innerDiameter", "minBendRadius"])
@pytest.mark.parametrize("value", [0, -3, "6"])
def test_sizes_are_positive_numbers(field, value):
    part = {"diameter": 6, "innerDiameter": 4}
    part[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_package(**part), get_partcad_schema())


def test_the_profile_rule_is_only_a_routed_parts():
    """A 'sketch' on an extrude, a 'length' on a wall: the routed rule does not reach them."""
    document = {
        "sketches": {"s": {"type": "basic", "circle": 1}},
        "parts": {
            "e": {"type": "extrude", "sketch": "s", "depth": 3},
            "w": {"type": "wall", "length": 1000, "height": 2500},
        },
    }
    jsonschema.validate(document, get_partcad_schema())
