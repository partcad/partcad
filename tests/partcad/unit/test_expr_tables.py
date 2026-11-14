#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The functions an expression works a value out of a table with.

'clamp', 'lerp', 'interpolate' and 'pick' for numbers, 'color_mix' and
'interpolate_color' for colours (see 'partcad.expr'). They are what lets a
parametric declaration - a material's density across its grades, a colour
across a range of compositions - be written from the values somebody measured
rather than from a formula nobody did. Pinned here: what each one answers, that
a value at a stop is the value written for it to the digit, and that every
mistake in a table is refused with what is wrong with it.
"""

import os
import sys

import pytest

import partcad as pc
from partcad import expr

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import css_color  # noqa: E402


def _value(expression, **values):
    return expr.substitute("%" + expression + "%", values)


# --------------------------------------------------------------------------- #
# Numbers                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "x, expected",
    [(-1, 0), (0, 0), (0.25, 0.25), (1, 1), (7, 1)],
)
def test_clamp_bounds_a_value(x, expected):
    assert _value("clamp(x, 0, 1)", x=x) == expected


def test_clamp_refuses_bounds_the_wrong_way_round():
    with pytest.raises(expr.ExpressionError, match="lower bound 3 is above the upper bound 2"):
        _value("clamp(1, 3, 2)")


@pytest.mark.parametrize("t, expected", [(0, 10.0), (0.5, 15.0), (1, 20.0), (2, 30.0), (-1, 0.0)])
def test_lerp_is_the_line_and_is_not_clamped(t, expected):
    assert _value("lerp(10, 20, t)", t=t) == expected


def test_interpolate_goes_through_the_points():
    stops = "[15, 30, 45], [0.15, 0.2, 0.25]"
    assert _value("interpolate(x, %s)" % stops, x=22.5) == pytest.approx(0.175)
    assert _value("interpolate(x, %s)" % stops, x=37.5) == pytest.approx(0.225)


@pytest.mark.parametrize("x, expected", [(0.1, 0.1), (0.2, 0.3), (0.3, 0.7)])
def test_interpolate_at_a_stop_is_the_value_written_for_it(x, expected):
    """To the digit: a catalogue's default at a measured grade has to be the measured value, not 0.30000000000000004."""
    assert _value("interpolate(x, [0.1, 0.2, 0.3], [0.1, 0.3, 0.7])", x=x) == expected


@pytest.mark.parametrize("x, expected", [(0, 1040), (10, 1040), (100, 1100), (1000, 1100)])
def test_interpolate_is_constant_past_the_ends(x, expected):
    """Not extrapolated: a value outside what was measured is a claim the declaration has to make itself."""
    assert _value("interpolate(x, [10, 100], [1040, 1100])", x=x) == expected


def test_an_interpolated_value_is_a_number_to_multiply():
    """'interpolate' answers a number, so it may be multiplied (see 'expr._is_numeric')."""
    assert _value("1000 * interpolate(x, [0, 1], [1, 2])", x=0.5) == 1500.0


@pytest.mark.parametrize(
    "expression, says",
    [
        ("interpolate(1, [1], [2])", "at least 2 stops"),
        ("interpolate(1, [1, 2], [2])", "2 stops and 1 values"),
        ("interpolate(1, [2, 1], [2, 3])", "increase strictly"),
        ("interpolate(1, [1, 1], [2, 3])", "increase strictly"),
        ("interpolate('a', [1, 2], [1, 2])", "the position is 'a', not a number"),
        ("interpolate(1, [1, 'b'], [1, 2])", "the stop 1 is 'b', not a number"),
        ("interpolate(1, [1, 2], [1, 'c'])", "the value 1 is 'c', not a number"),
        ("interpolate(1, 2, [1, 2])", "the stops is 2, not a list"),
    ],
)
def test_interpolate_refuses_a_table_that_is_not_one(expression, says):
    with pytest.raises(expr.ExpressionError, match=says):
        _value(expression)


def test_pick_looks_a_key_up():
    tempers = "['O', 'T4', 'T6'], [55e6, 145e6, 276e6]"
    assert _value("pick(temper, %s)" % tempers, temper="T6") == 276e6
    assert _value("pick(temper, %s)" % tempers, temper="O") == 55e6
    # A table of numbers answers a number, so it may be multiplied.
    assert _value("2 * pick(temper, %s)" % tempers, temper="T4") == 290e6


def test_pick_names_the_key_and_the_keys_it_is_not_one_of():
    with pytest.raises(expr.ExpressionError, match=r"'T7' is not one of the keys 'O', 'T6'"):
        _value("pick(temper, ['O', 'T6'], [1, 2])", temper="T7")


def test_pick_refuses_tables_of_different_lengths():
    with pytest.raises(expr.ExpressionError, match="2 keys and 1 values"):
        _value("pick('O', ['O', 'T6'], [1])")


def test_what_pick_answers_from_text_is_not_a_number_to_multiply():
    """Multiplying text repeats it, which is how an expression allocates a gigabyte: refused unless certainly a number."""
    with pytest.raises(expr.ExpressionError, match="only numbers may be multiplied"):
        _value("1000000000 * pick(1, [1], ['x'])")


# --------------------------------------------------------------------------- #
# Colours                                                                     #
# --------------------------------------------------------------------------- #


def test_color_mix_mixes_in_oklab_as_css_does():
    """CSS's 'color-mix(in oklab, white, black)' is oklab(0.5 0 0), which is #636363 in sRGB."""
    assert _value("color_mix('white', 'black', 0.5)") == "#636363"
    assert _value("color_mix('red', 'blue', 0.5)") == "#8C53A2"


@pytest.mark.parametrize("t, expected", [(0, "#C91A09"), (-3, "#C91A09"), (1, "#123456"), (4, "#123456")])
def test_color_mix_is_each_colour_at_its_end_and_clamps_the_share(t, expected):
    assert _value("color_mix('#c91a09', 'rgb(18 52 86)', t)", t=t) == expected


def test_color_mix_mixes_alpha_premultiplied():
    """A colour half see-through gets half the say in the hue, as CSS mixes it; the alpha is the mean."""
    mixed = css_color.parse(_value("color_mix('#ff000080', '#0000ff', 0.5)"))
    assert mixed[3] == pytest.approx(0.75, abs=1 / 255)
    # Nearer the opaque blue than an unweighted mix of the two hues would be.
    assert mixed[2] > css_color.parse(_value("color_mix('#ff0000', '#0000ff', 0.5)"))[2]


def test_color_mix_answers_rgba_only_when_not_opaque():
    assert _value("color_mix('#ffffff', '#000000', 0.5)") == "#636363"
    assert _value("color_mix('#ffffff00', '#ffffff', 0.5)") == "#FFFFFF80"


def test_color_mix_refuses_what_is_not_a_css_colour():
    with pytest.raises(expr.ExpressionError, match="the first colour is 'nope', which is not a CSS colour"):
        _value("color_mix('nope', 'red', 0.5)")
    with pytest.raises(expr.ExpressionError, match="the second colour is 3"):
        _value("color_mix('red', 3, 0.5)")


def test_interpolate_color_goes_through_the_stops():
    stops = "[0, 0.5, 1], ['#ff0000', '#00ff00', '#0000ff']"
    assert _value("interpolate_color(x, %s)" % stops, x=0) == "#FF0000"
    assert _value("interpolate_color(x, %s)" % stops, x=0.5) == "#00FF00"
    assert _value("interpolate_color(x, %s)" % stops, x=1) == "#0000FF"
    # Between two stops, the two mixed as 'color_mix' mixes them.
    assert _value("interpolate_color(x, %s)" % stops, x=0.75) == _value("color_mix('#00ff00', '#0000ff', 0.5)")
    # And clamped at the ends.
    assert _value("interpolate_color(x, %s)" % stops, x=-2) == "#FF0000"
    assert _value("interpolate_color(x, %s)" % stops, x=9) == "#0000FF"


@pytest.mark.parametrize(
    "expression, says",
    [
        ("interpolate_color(0, [0], ['red'])", "at least 2 stops"),
        ("interpolate_color(0, [0, 1], ['red'])", "2 stops and 1 colours"),
        ("interpolate_color(0, [1, 0], ['red', 'blue'])", "increase strictly"),
        ("interpolate_color(0.5, [0, 1], ['red', 'bleu'])", "the colour 1 is 'bleu', which is not a CSS colour"),
    ],
)
def test_interpolate_color_refuses_a_table_that_is_not_one(expression, says):
    with pytest.raises(expr.ExpressionError, match=says):
        _value(expression)


def test_oklab_round_trips_srgb():
    """What the mixing rests on: a colour converted to Oklab and back is the colour it was."""
    for text in ("#000000", "#FFFFFF", "#C91A09", "#123456", "#00FF00", "#808080"):
        rgba = css_color.parse(text)
        assert css_color.mix_oklab(rgba, rgba, 0.5) == rgba


def test_the_functions_are_there_for_every_expression():
    """Not only a CMF declaration's: an interface's or a part's expression has them too."""
    for name in ("clamp", "lerp", "interpolate", "pick", "color_mix", "interpolate_color"):
        assert name in expr.SAFE_NAMES
