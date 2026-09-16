#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How big a shape is and how much of it there is, as 'pc info' reports it.

Two numbers a reader of a part wants before any other, and neither of them can
be read off a declaration: a part is a script, a file or a boolean of two
others, so the only way to know its size is to have built it. That is why they
are in 'pc info' at all, and why `/pc:describe` starts from them rather than
from a projection somebody estimated a size off.

The measuring itself is OCCT's and happens in a sandbox, which is not reachable
from here. What is covered here is what is done with the answer: which keys it
becomes, that 'size' agrees with the bounds it was worked out from, that the
tolerance OCCT pads a bounding box by does not reach the reader, and that a
shape which cannot be measured costs 'pc info' nothing but those two keys.
"""

import asyncio

import pytest

from partcad.shape import Shape, measured


class _Shape(Shape):
    """The little a measurement needs of a shape, and nothing that builds one."""

    def __init__(self, box=(0, 0, 0, 10, 20, 30), solidity=None, unbuilt=False, raises=None):
        """A shape that answers the two measurements with whatever it was given."""
        super().__init__("//test", {"name": "thing"})
        self.name = "thing"
        self._box = box
        self._solidity = solidity
        self._unbuilt = unbuilt
        self._raises = raises
        self.asked = 0

    async def get_wrapped(self, ctx):
        """Something, or nothing for a shape whose script raised."""
        return None if self._unbuilt else object()

    async def get_bounding_box_async(self, ctx):
        """The box as OCCT would return it - padded bounds and all."""
        self.asked += 1
        if self._raises:
            raise self._raises
        return self._box

    async def get_solidity_async(self, ctx):
        """What the solidity wrapper reports, or None for a shape holding no solid."""
        self.asked += 1
        if self._raises:
            raise self._raises
        return self._solidity


def _measure(shape):
    """The measurements as 'pc info' would print them.

    No context is passed: nothing reached from here ever looks at one.
    """
    return asyncio.run(shape.measurements_async(None))


def test_the_bounding_box_is_reported_as_where_it_is_and_how_large():
    """Three triples: a shape 10 wide starting at -1 is not a shape 10 wide at 0."""
    info = _measure(_Shape(box=(-1.0, 0.0, 2.0, 9.0, 20.0, 5.0)))

    assert info["BoundingBox"] == {
        "min": [-1.0, 0.0, 2.0],
        "max": [9.0, 20.0, 5.0],
        "size": [10.0, 20.0, 3.0],
    }


def test_the_tolerance_occt_pads_the_box_by_does_not_reach_the_reader():
    """A 120 mm block measures 120.0000002, and that is OCCT leaving itself room.

    Every other caller of the measurement wants the padding - an exploded view
    that overlapped by a tolerance would be wrong - so it comes off here and
    nowhere else.
    """
    fuzz = 1e-7
    info = _measure(_Shape(box=(-fuzz, -fuzz, -fuzz, 120 + fuzz, 40 + fuzz, 2 + fuzz)))

    assert info["BoundingBox"] == {
        "min": [0.0, 0.0, 0.0],
        "max": [120.0, 40.0, 2.0],
        "size": [120.0, 40.0, 2.0],
    }


def test_a_bound_that_rounds_to_zero_from_below_is_not_minus_nought():
    """It is the same number and it reads as a different one."""
    assert measured(-1e-9) == 0.0
    assert str(measured(-1e-9)) == "0.0"


def test_the_size_agrees_with_the_bounds_it_was_worked_out_from():
    """Worked out from the rounded bounds rather than rounded itself.

    Subtracting first and rounding afterwards can leave the three disagreeing by
    the last digit, and 'size' is the one of them anybody reads out loud.
    """
    info = _measure(_Shape(box=(0.1, 0.2, 0.3, 0.30000000000000004, 0.7, 1.0)))
    box = info["BoundingBox"]

    for axis in range(3):
        assert box["size"][axis] == pytest.approx(box["max"][axis] - box["min"][axis], abs=1e-9)


def test_the_volume_and_how_many_solids_it_is_of():
    """More than one solid in a part is worth saying: it is deliberate or a bug."""
    info = _measure(_Shape(solidity={"solids": 2, "volume": 9600.0, "valid": True}))

    assert info["Volume"] == 9600.0
    assert info["Solids"] == 2


def test_a_shape_with_no_solid_in_it_has_no_volume_to_report():
    """A sketch, a shell, a wire. Nought and "none to speak of" differ."""
    info = _measure(_Shape(solidity={"solids": 0, "volume": None, "valid": None}))

    assert "Volume" not in info
    assert "Solids" not in info
    assert "BoundingBox" in info


def test_a_volume_that_is_negative_is_reported_as_it_stands():
    """Faces oriented inward: a real thing to know, not a sign to drop."""
    info = _measure(_Shape(solidity={"solids": 1, "volume": -9600.0, "valid": False}))

    assert info["Volume"] == -9600.0


def test_a_shape_that_did_not_build_is_not_measured():
    """'pc info' on a part whose script raised is a common thing to do.

    Asked once, rather than left to the two measurements below, which would each
    start a sandbox to be told the same thing.
    """
    shape = _Shape(unbuilt=True)

    assert _measure(shape) == {}
    assert shape.asked == 0


def test_neither_measurement_can_take_the_other_down():
    """Both are measured in a sandbox, so either can fail on its own.

    'pc info' still has a part's configuration, its hash and its dependencies to
    report, which is what it was asked for.
    """
    assert _measure(_Shape(raises=Exception("no sandbox"))) == {}


def test_an_empty_bounding_box_is_left_out_rather_than_invented():
    """A shape that built and occupies nothing has no size to state."""
    assert _measure(_Shape(box=None)) == {}
