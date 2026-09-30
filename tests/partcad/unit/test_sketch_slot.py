#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'slot' outline of a "basic" sketch.

A slot is a rectangle with semicircular ends - two arcs and two lines - and it
is what a slotted hole is. The shape is checked by measuring it rather than by
asserting that something was produced: an outline that closes the wrong way,
puts the arcs at the wrong radius, or anchors the slot in the wrong place, still
builds a face.
"""

import asyncio
import io
import math

import pytest

import partcad as pc
from partcad import shape_envelope

PACKAGE = "tests/partcad/unit/data/sketch_slot/partcad.yaml"


@pytest.fixture(scope="module")
def project():
    return pc.Context(PACKAGE).get_project("//")


def _measured(project, name):
    """The area, the size of the bounding box and its centre, in millimetres.

    The core only ever holds an opaque BREP envelope - nothing above the sandbox
    touches a live OCCT object - so the payload is read back into one here.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Builder
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS_Shape

    ctx = project.ctx
    envelope = asyncio.run(project.get_sketch(name).get_wrapped(ctx))
    shape = TopoDS_Shape()
    BRepTools.Read_s(
        shape,
        io.BytesIO(shape_envelope.brep_plain(envelope[shape_envelope.KEY_BREP])),
        BRep_Builder(),
    )

    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, properties)
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    x_min, y_min, _, x_max, y_max, _ = box.Get()
    return (
        properties.Mass(),
        (x_max - x_min, y_max - y_min),
        ((x_min + x_max) / 2.0, (y_min + y_max) / 2.0),
    )


def _slot_area(length, width):
    """The straight part plus the two ends, which together are one circle."""
    return (length - width) * width + math.pi * (width / 2.0) ** 2


def test_a_slot_is_the_shape_a_slotted_hole_is(project):
    area, size, _ = _measured(project, "slot")
    assert area == pytest.approx(_slot_area(30.0, 4.0))
    assert size == pytest.approx((30.0, 4.0))


def test_a_slot_starts_where_the_hole_would_have_been(project):
    """Its origin is the centre of the *first* rounded end, not the middle.

    A slot is a hole that may also sit somewhere else, so it begins where the
    plain hole was and runs from there: the port keeps its coordinates when the
    opening it marks is slotted.
    """
    _, _, centre = _measured(project, "slot")
    # The first end is centred on the origin, so the outline runs from -2 to 28.
    assert centre == pytest.approx((13.0, 0.0))


def test_a_slot_may_be_turned_and_placed(project):
    area, size, centre = _measured(project, "slot-placed")
    assert area == pytest.approx(_slot_area(30.0, 4.0))
    assert size == pytest.approx((4.0, 30.0))
    # Turned a quarter turn about its first end, which is at (5, 1): the slot
    # runs up from there, so the box is centred 13mm above it.
    assert centre == pytest.approx((5.0, 14.0))


def test_a_slot_with_no_straight_part_is_a_circle(project):
    """The degenerate case is the circle it should be, not an error and not a gap.

    And it is centred on the origin, because with no straight part the first
    rounded end is the whole of it.
    """
    slot = _measured(project, "slot-as-long-as-it-is-wide")
    circle = _measured(project, "circle")
    assert slot[0] == pytest.approx(circle[0])
    assert slot[1] == pytest.approx(circle[1])
    assert slot[2] == pytest.approx(circle[2])


def test_slots_may_be_cut_out_of_another_shape(project):
    area, size, _ = _measured(project, "plate-with-slots")
    assert size == pytest.approx((60.0, 20.0))
    assert area == pytest.approx(60.0 * 20.0 - 2 * _slot_area(20.0, 4.0))


def test_a_slot_reads_the_sketch_parameters(project):
    """One sketch draws the boundary of every slotted port of an interface family."""
    area, size, _ = _measured(project, "slotted")
    assert size == pytest.approx((30.0, 4.0))
    assert area == pytest.approx(_slot_area(30.0, 4.0))

    area, size, _ = _measured(project, "slotted;size=6,length=20")
    assert size == pytest.approx((20.0, 6.0))
    assert area == pytest.approx(_slot_area(20.0, 6.0))


def test_a_slot_shorter_than_it_is_wide_is_reported(project):
    """'length' is measured over the rounded ends, so it cannot be the smaller one.

    Reported the way every other failed shape is - recorded on the sketch, which
    produces nothing - rather than raised: one unbuildable sketch costs the
    caller that sketch.
    """
    sketch = project.get_sketch("slot-too-narrow")
    assert asyncio.run(sketch.get_wrapped(project.ctx)) is None
    assert any("slot" in error.lower() for error in sketch.errors), sketch.errors
