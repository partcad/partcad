#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object's ``offset:`` does to its geometry.

``offset:`` is documented as "the offset to apply to the CAD model when this
object is used", and every reader of the geometry - an export, a render, a route,
a part placed in an assembly - is supposed to see the moved shape. The wrapper
that applies it used build123d's ``relocate()``, which keeps the geometry exactly
where it is and only re-labels the frame it is measured in, so the field had no
effect on anything at all:

    Solid.make_box(10, 20, 30).relocate(Location([[100, 0, 0], [0, 0, 1], 0]))
        -> x = [0 .. 10]
    Solid.make_box(10, 20, 30).moved(Location([[100, 0, 0], [0, 0, 1], 0]))
        -> x = [100 .. 110]

This file holds the wrapper to the second one. It stubs build123d rather than
importing it: the distinction under test is which method the wrapper calls, the
stub makes calling the wrong one a failure rather than a silent no-op, and a unit
test that needed the CAD stack would not run where the rest of these do.
"""

import os
import sys
import types

import pytest

WRAPPERS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "partcad", "wrappers")


class _Location:
    def __init__(self, *args):
        self.args = args


class _Solid:
    """Enough of build123d's Solid for the wrapper, and no more."""

    def __init__(self):
        self.wrapped = None
        self.moved_to = None

    @staticmethod
    def make_box(*_args, **_kwargs):
        return _Solid()

    def moved(self, location):
        moved = _Solid()
        moved.wrapped = ("moved", self.wrapped, location.args)
        return moved

    def relocate(self, _location):
        raise AssertionError(
            "'offset:' has to move the geometry: relocate() only re-labels the frame it is measured in"
        )

    def scale(self, factor):
        scaled = _Solid()
        scaled.wrapped = ("scaled", self.wrapped, factor)
        return scaled


@pytest.fixture
def transform(monkeypatch):
    """'wrapper_transform' with a stub build123d behind it."""
    stub = types.ModuleType("build123d")
    stub.Solid = _Solid
    stub.Location = _Location
    monkeypatch.setitem(sys.modules, "build123d", stub)
    monkeypatch.syspath_prepend(os.path.abspath(WRAPPERS))
    # Imported here rather than at module scope: importing it pulls in the
    # wrapper's own sys.path games, and the stub has to be in place first.
    import wrapper_transform

    return wrapper_transform


def test_offset_moves_the_geometry(transform):
    """The shape comes back moved, which is what the field promises."""
    offset = [[100, 0, 0], [0, 0, 1], 0]
    result = transform.process({"operation": "offset", "shape": "<brep>", "offset": offset})
    assert result == ("moved", "<brep>", ([100, 0, 0], [0, 0, 1], 0))


def test_offset_passes_the_whole_location_through(transform):
    """A rotation reaches build123d as it was written, axis and angle included."""
    offset = [[0, 0, 0], [0, 1, 0], 90]
    result = transform.process({"operation": "offset", "shape": "<brep>", "offset": offset})
    assert result == ("moved", "<brep>", ([0, 0, 0], [0, 1, 0], 90))


def test_scale_is_untouched(transform):
    """The other operations of the same wrapper still work the way they did."""
    result = transform.process({"operation": "scale", "shape": "<brep>", "scale": 2.0})
    assert result == ("scaled", "<brep>", 2.0)


def test_unknown_operation_is_refused(transform):
    with pytest.raises(ValueError):
        transform.process({"operation": "translate", "shape": "<brep>"})
