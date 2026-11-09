#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How big a shape is and how much of it there is, measured where OCCT lives.

'wrappers/wrapper_measure.py' is the sandbox half of what 'pc info' reports: the
core never holds a live OCP object, so the box and the volume are taken here and
travel back as a handful of floats. 'test_shape_measurements' covers everything
around that - the cache entry, the failure that is not remembered, the keys the
numbers become - with the sandbox replaced. This is the other side: the numbers
themselves, against real geometry.

Two of them are worth stating rather than trusting. OCCT pads a bounding box by
the shape's own tolerance, so a 10 mm box reports 10.0000002 unless the gap is
dropped - which is the difference between a size a reader recognises and one
they have to round in their head. And a volume is taken per solid rather than
over the whole shape, so that a compound of several is reported as several; a
shape holding no solid at all has no volume rather than one of nought, because a
sketch and a box of zero height are not the same answer.
"""

import math
import os
import sys

import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_measure  # noqa: E402

BOX = (10.0, 20.0, 30.0)
BOX_VOLUME = BOX[0] * BOX[1] * BOX[2]

# Tighter than the tolerance OCCT would have padded the box by, so that a test
# of "the gap was dropped" cannot pass on a box that still carries one.
PRECISE = 1e-9


def _box(size=BOX):
    """A solid, at the origin."""
    return BRepPrimAPI_MakeBox(*size).Shape()


def _moved(shape, offset=(100.0, 0.0, 0.0)):
    """The same shape somewhere else, so a box says where as well as how large."""
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(*offset))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _compound(*children):
    """Several shapes as one, which is what a part with more than one solid is."""
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for child in children:
        builder.Add(compound, child)
    return compound


#
# The box
#


def test_a_box_measures_its_own_extent_and_not_its_tolerance():
    """OCCT grows a bounding box by the shape's tolerance; the gap is dropped.

    Without that a 10 mm block reports 10.0000002, which every other caller of
    the bounding box wants - an exploded view that overlapped by a tolerance
    would be wrong - and no reader of 'pc info' does.
    """
    box = wrapper_measure._bbox(_box())

    assert box == pytest.approx([0.0, 0.0, 0.0, 10.0, 20.0, 30.0], abs=PRECISE)


def test_the_box_says_where_the_shape_is_as_well_as_how_large():
    """A shape 10 wide starting at 100 is not a shape 10 wide at the origin."""
    box = wrapper_measure._bbox(_moved(_box()))

    assert box == pytest.approx([100.0, 0.0, 0.0, 110.0, 20.0, 30.0], abs=PRECISE)


def test_a_shape_occupying_nothing_has_no_box():
    """An empty compound built without error still bounds nothing."""
    assert wrapper_measure._bbox(_compound()) is None


#
# The volume, per solid
#


def test_a_single_solid_is_one_volume():
    """The arithmetic, against a shape whose volume is known by multiplication."""
    assert wrapper_measure._volumes(_box()) == pytest.approx([BOX_VOLUME])


def test_several_solids_are_reported_one_by_one_largest_first():
    """Summed here, an inverted solid would vanish into a larger correct one.

    So the sizes come back separately and in a stated order, and what adds them
    up does so knowing how many there were.
    """
    small = _moved(_box((1.0, 1.0, 1.0)))
    volumes = wrapper_measure._volumes(_compound(small, _box()))

    assert volumes == pytest.approx([BOX_VOLUME, 1.0])


def test_a_shape_with_no_solid_in_it_has_no_volumes_at_all():
    """A shell is a skin: it bounds something without being it."""
    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()

    assert wrapper_measure._volumes(shell) == []


#
# Both together, which is what the operation exists for
#


def test_one_pass_answers_everything_pc_info_asks():
    """The box, the volume and the count, so the sandbox is started once."""
    measured = wrapper_measure._measurements(_box())

    assert measured["bbox"] == pytest.approx([0.0, 0.0, 0.0, 10.0, 20.0, 30.0], abs=PRECISE)
    assert measured["volume"] == pytest.approx(BOX_VOLUME)
    assert measured["solids"] == 1


def test_more_than_one_solid_is_summed_and_counted():
    """The count is what makes the sum readable - and is worth seeing by itself."""
    measured = wrapper_measure._measurements(_compound(_box(), _moved(_box())))

    assert measured["volume"] == pytest.approx(2 * BOX_VOLUME)
    assert measured["solids"] == 2


def test_a_shape_that_encloses_nothing_has_no_volume_rather_than_nought():
    """A sketch, a shell, a wire. It still has a size, and that is still worth
    reporting - so the box survives a volume that does not apply."""
    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()
    measured = wrapper_measure._measurements(shell)

    assert measured["volume"] is None
    assert measured["solids"] == 0
    assert measured["bbox"] == pytest.approx([0.0, 0.0, 0.0, 10.0, 20.0, 30.0], abs=PRECISE)


#
# The displacement: the material and every void sealed inside it
#


def _hollow():
    """A 10 mm cube with a 2 mm cube of nothing sealed inside it: 992 mm^3 of material, 1000 displaced."""
    void = BRepPrimAPI_MakeBox(gp_Pnt(4.0, 4.0, 4.0), 2.0, 2.0, 2.0).Shape()
    return BRepAlgoAPI_Cut(_box((10.0, 10.0, 10.0)), void).Shape()


def _drilled():
    """A 10 mm cube with a hole of radius 1 mm right through it."""
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5.0, 5.0, -1.0), gp_Dir(0.0, 0.0, 1.0)), 1.0, 12.0).Shape()
    return BRepAlgoAPI_Cut(_box((10.0, 10.0, 10.0)), hole).Shape()


def test_a_sealed_void_is_displaced_and_is_not_material():
    """The void is inside the outer shell, so it is pushed aside with the rest; it is still not volume."""
    hollow = _hollow()

    assert wrapper_measure._measurements(hollow)["volume"] == pytest.approx(992.0)
    assert wrapper_measure._displacement(hollow) == {"displacement": pytest.approx(1000.0), "solids": 1, "cavities": 1}


def test_a_hole_right_through_is_not_displaced():
    """Water reaches a hole that goes through, so a drilled cube displaces only its material."""
    drilled = _drilled()
    volume = wrapper_measure._measurements(drilled)["volume"]

    # The 10 mm of the hole that is inside the cube, at a radius of 1 mm.
    assert volume == pytest.approx(1000.0 - math.pi * 10.0)
    assert wrapper_measure._displacement(drilled) == {"displacement": pytest.approx(volume), "solids": 1, "cavities": 0}


def test_a_solid_with_no_void_displaces_exactly_its_volume():
    """Integrated the way the volume is, so the two cannot differ in the last digit."""
    assert wrapper_measure._displacement(_box())["displacement"] == wrapper_measure._measurements(_box())["volume"]


def test_several_solids_each_displace_their_own():
    """Added up the way their volumes are, wherever each of them is."""
    displaced = wrapper_measure._displacement(_compound(_hollow(), _moved(_box())))

    assert displaced == {"displacement": pytest.approx(1000.0 + BOX_VOLUME), "solids": 2, "cavities": 1}


def test_a_shape_with_no_solid_in_it_displaces_nothing_rather_than_nought():
    """A skin bounds something without being it, as it has no volume."""
    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()

    assert wrapper_measure._displacement(shell) == {"displacement": None, "solids": 0, "cavities": 0}


#
# What the sandbox is actually asked
#


def test_the_operation_names_are_the_ones_the_core_calls():
    """'bbox' on its own predates 'measurements', and still has callers of its own."""
    assert wrapper_measure.process({"operation": "bbox", "shape": _box()}) == pytest.approx(
        [0.0, 0.0, 0.0, 10.0, 20.0, 30.0], abs=PRECISE
    )
    assert wrapper_measure.process({"operation": "measurements", "shape": _box()})["solids"] == 1
    assert wrapper_measure.process({"operation": "displacement", "shape": _hollow()})["cavities"] == 1


def test_an_operation_nobody_implements_is_refused_by_name():
    """A wrapper answering a request it does not understand would report a
    measurement of nothing as a measurement."""
    with pytest.raises(ValueError, match="strides"):
        wrapper_measure.process({"operation": "strides", "shape": _box()})
