#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the vector font the port labels are drawn with.

'stroke_text' runs inside the render sandbox but is pure Python and imports
nothing, so it is exercised here directly rather than through a render.
"""

import os
import string
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import stroke_text  # noqa: E402


def _points(text):
    """Every point of every stroke of 'text', in one flat list."""
    return [point for polyline in stroke_text.polylines(text) for point in polyline]


def test_every_polyline_has_at_least_two_points():
    """A single point is not a stroke: it would draw nothing at all."""
    for polyline in stroke_text.polylines(string.printable.strip()):
        assert len(polyline) >= 2


def test_a_name_a_port_can_have_is_drawable():
    """The characters PartCAD's own names are made of all have a glyph.

    A port name is built out of the interface names above it, so it is letters,
    digits and the separators PartCAD itself inserts.
    """
    for char in string.ascii_letters + string.digits + "-_./:":
        assert char.upper() in stroke_text._GLYPHS or char in stroke_text._GLYPHS


def test_unknown_characters_still_take_up_space():
    """Something a caller can see, rather than a silent gap."""
    assert stroke_text.polylines("é")
    assert stroke_text.width("é") == stroke_text.width("A")


def test_capitals_are_one_unit_tall():
    """The caller scales by the text height it wants, so the cap height is 1."""
    ys = [y for _x, y in _points(string.ascii_uppercase + string.digits)]
    assert max(ys) == 1.0
    assert min(ys) >= 0.0


def test_lowercase_is_drawn_as_small_capitals():
    """Same shapes, smaller - which is what keeps the font to one alphabet."""
    lower = _points("a")
    upper = _points("A")
    assert len(lower) == len(upper)
    assert max(y for _x, y in lower) == pytest.approx(stroke_text.SMALL_CAPS)
    assert max(y for _x, y in upper) == 1.0


def test_the_text_starts_at_the_origin_and_advances_to_the_right():
    """Everything a caller has to know to place a label: where it begins and
    how wide it ends up."""
    xs = [x for x, _y in _points("MMM")]
    assert min(xs) == 0.0
    assert max(xs) <= stroke_text.width("MMM")
    assert stroke_text.width("MMM") == 3 * stroke_text.width("M")


def test_a_space_draws_nothing_but_still_advances():
    """A gap is a gap, not a glyph that happens to be blank."""
    assert stroke_text.polylines(" ") == []
    assert stroke_text.width("A A") > stroke_text.width("AA")
