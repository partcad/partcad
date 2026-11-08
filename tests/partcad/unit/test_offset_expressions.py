#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Expressions in a part's 'offset' and 'scale' ('shape_config.transform_of').

The schema has always taken a '%...%' expression in a location, and nothing
worked one out: an 'offset' holding one reached the sandbox that moved the part
as text and failed there. These hold that it is resolved over the parameters
of the declaration that carries it, for each instance with its own values, and
that the declaration itself keeps the expression. Nothing here builds a shape:
what a part's wrapper is asked to do is 'finish_request()', and that is what is
read.
"""

import pytest

import partcad as pc
from partcad.shape_config import transform_of

PACKAGE = """
parts:
  plate:
    type: step
    parameters:
      thickness:
        type: float
        default: 4
    offset: [[0, 0, "%thickness / 2%"], [0, 0, 1], "%thickness * 10%"]
    scale: "%thickness / 4%"
  fixed:
    type: step
    offset: [[1, 2, 3], [0, 0, 1], 0]
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    for name in ("plate", "fixed"):
        (tmp_path / ("%s.step" % name)).write_text("")
    return pc.Context(str(tmp_path))


def test_an_expression_in_an_offset_is_worked_out_over_the_parameters():
    config = {"parameters": {"d": {"type": "float", "default": 6}}, "offset": [[0, 0, "%d / 2%"], [0, 0, 1], 0]}
    assert transform_of(config, "offset") == [[0, 0, 3], [0, 0, 1], 0]
    # What it was written as is left alone.
    assert config["offset"] == [[0, 0, "%d / 2%"], [0, 0, 1], 0]


def test_a_transform_that_is_numbers_or_absent_is_what_it_was():
    assert transform_of({"offset": [[1, 2, 3], [0, 0, 1], 45]}, "offset") == [[1, 2, 3], [0, 0, 1], 45]
    assert transform_of({"scale": 2}, "scale") == 2
    assert transform_of({}, "offset") is None
    assert transform_of({"offset": None}, "offset") is None


def test_an_expression_that_cannot_be_worked_out_is_reported():
    pc.logging.reset_errors()
    assert transform_of({"offset": [[0, 0, "%nothing%"], [0, 0, 1], 0]}, "offset", "//:thing") == [
        [0, 0, "%nothing%"],
        [0, 0, 1],
        0,
    ]
    assert pc.logging.had_errors


def test_a_part_is_asked_to_move_by_its_own_values(ctx):
    """What every part's wrapper is asked to do, and what the core does where a wrapper does not."""
    plate = ctx.get_part("plate")
    assert plate.finish_request()["offset"] == [[0, 0, 2], [0, 0, 1], 40]
    assert plate.finish_request()["scale"] == 1
    thick = ctx.get_part("plate;thickness=8")
    assert thick.finish_request()["offset"] == [[0, 0, 4], [0, 0, 1], 80]
    assert thick.finish_request()["scale"] == 2
    # The declaration still holds the expressions the next instance resolves.
    assert plate.config["offset"][0][2] == "%thickness / 2%"
    assert ctx.get_part("fixed").finish_request()["offset"] == [[1, 2, 3], [0, 0, 1], 0]


def test_two_instances_moved_by_their_values_are_two_cache_entries(ctx):
    keys = {ctx.get_part("plate;thickness=%d" % value).hash.get() for value in (4, 8)}
    assert None not in keys
    assert len(keys) == 2
