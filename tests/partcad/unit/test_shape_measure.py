#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A shape is measured once, however often it is met - and to the same numbers.

'shape_measure.Measurer' integrates each solid once per 'TShape', moves those
numbers to wherever else the solid is placed, and works a compound out from its
children instead of integrating it whole. All of that is only worth having if
the answer is the one OCCT gives for the shape as it stands, so every test here
compares against '_integrated_whole()': the measuring as it was done before, one
'VolumeProperties' per solid the explorer meets and 'GProp_GProps.Add()' over
all of them, with the box OCCT draws round the whole shape.
"""

import math
import os
import sys

import pytest

import partcad as pc

# 'partcad' before OCP: see the note in test_mass_properties.
# isort: split

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import shape_measure  # noqa: E402


def _integrated_whole(shape):
    """What 'shape_measure.measurements()' answered before it measured anything once.

    Kept here as the reference the new arithmetic is held to: every solid the
    explorer meets integrated where it stands, added up by OCCT itself, and the
    box drawn round the whole shape.
    """
    solids = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        solids.append(props)
        explorer.Next()
    found = sorted((props.Mass() for props in solids), reverse=True)
    measured = {
        "bbox": shape_measure.bbox(shape),
        "volume": sum(found) if found else None,
        "solids": len(found),
        # Not integrated, and not worked out from children: counted on the
        # whole shape, as it always was.
        "freeShells": shape_measure.free_shells(shape),
    }
    if solids and all(props.Mass() > 0.0 for props in solids):
        total = GProp_GProps()
        for props in solids:
            total.Add(props)
        centre = total.CentreOfMass()
        matrix = total.MatrixOfInertia()
        measured["centroid"] = [centre.X(), centre.Y(), centre.Z()]
        measured["unitInertia"] = [[matrix.Value(row, col) for col in (1, 2, 3)] for row in (1, 2, 3)]
    return measured


def _assert_same(measured, expected):
    """The same measurements, to float rounding - and the box exactly."""
    assert set(measured) == set(expected)
    assert measured["solids"] == expected["solids"]
    assert measured["freeShells"] == expected["freeShells"]
    # The union of the children's boxes is the box OCCT draws round the whole:
    # min and max are exact, so this is equality, not closeness.
    assert measured["bbox"] == expected["bbox"]
    if expected["volume"] is None:
        assert measured["volume"] is None
    else:
        assert measured["volume"] == pytest.approx(expected["volume"], rel=1e-12)
    if "centroid" in expected:
        size = max(abs(value) for value in expected["bbox"])
        assert measured["centroid"] == pytest.approx(expected["centroid"], rel=1e-9, abs=size * 1e-12)
        scale = max(abs(value) for row in expected["unitInertia"] for value in row)
        for row in range(3):
            assert measured["unitInertia"][row] == pytest.approx(expected["unitInertia"][row], abs=scale * 1e-9)


def _compound(*children):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for child in children:
        builder.Add(compound, child)
    return compound


def _placed(shape, translation=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0), degrees=0.0):
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(*axis)), math.radians(degrees))
    trsf.SetTranslationPart(gp_Vec(*translation))
    return shape.Moved(TopLoc_Location(trsf))


def _box(x=10.0, y=20.0, z=30.0):
    return BRepPrimAPI_MakeBox(x, y, z).Shape()


def _distinct_solids():
    """Solids of different kinds and sizes, none sharing a 'TShape'."""
    return [
        _placed(_box(), (100.0, 0.0, 0.0)),
        _placed(BRepPrimAPI_MakeCylinder(4.0, 25.0).Shape(), (0.0, 50.0, -10.0), (1.0, 1.0, 0.0), 33.0),
        _placed(BRepPrimAPI_MakeSphere(7.5).Shape(), (-40.0, -40.0, 12.0)),
        _placed(BRepPrimAPI_MakeCone(6.0, 1.0, 14.0).Shape(), (5.0, 5.0, 5.0), (0.2, -1.0, 0.4), 120.0),
    ]


def _wire():
    polygon = BRepBuilderAPI_MakePolygon(gp_Pnt(0, 0, 0), gp_Pnt(50, 0, 0), gp_Pnt(50, 60, 0), True)
    return polygon.Wire()


def _compounds():
    """Several compounds, each a different way of meeting a solid more than once."""
    distinct = _distinct_solids()
    block = _box(12.0, 8.0, 5.0)
    placements = [
        _placed(block, (25.0 * index, 7.0 * index, -3.0 * index), (1.0, 2.0, 3.0), 17.0 * index) for index in range(6)
    ]
    inner = _compound(*distinct[:2])
    return {
        "distinct solids": _compound(*distinct),
        "one solid placed six times": _compound(*placements),
        "a compound of compounds sharing a child": _compound(
            inner, _placed(inner, (0.0, 0.0, 200.0)), distinct[2], _compound(distinct[2], distinct[3])
        ),
        "the same child twice in one place": _compound(distinct[0], distinct[0], distinct[1]),
        "solids, a face and a wire": _compound(
            distinct[0], TopExp_Explorer(_box(), TopAbs_FACE).Current(), _wire(), distinct[3]
        ),
        "a solid turned inside out beside a correct one": _compound(distinct[0], distinct[1].Reversed()),
        "a skin beside a solid": _compound(TopExp_Explorer(_box(), TopAbs_SHELL).Current(), distinct[2]),
        "nothing at all": _compound(),
        "a placed compound": _placed(_compound(*placements[:3]), (-500.0, 3.0, 9.0), (0.0, 1.0, 0.0), 90.0),
    }


@pytest.mark.parametrize("name", list(_compounds()))
def test_a_compound_measures_what_it_measured_integrated_whole(name):
    shape = _compounds()[name]

    _assert_same(shape_measure.measurements(shape), _integrated_whole(shape))


def test_a_single_solid_measures_what_it_measured_before():
    shape = _distinct_solids()[1]

    _assert_same(shape_measure.measurements(shape), _integrated_whole(shape))


def test_each_child_measures_what_it_measures_on_its_own():
    """Measured after the compound, out of what the compound measured."""
    shape = _compounds()["a compound of compounds sharing a child"]
    measurer = shape_measure.Measurer()
    measurer.measurements(shape)

    from OCP.TopoDS import TopoDS_Iterator

    children = TopoDS_Iterator(shape)
    while children.More():
        _assert_same(measurer.measurements(children.Value()), _integrated_whole(children.Value()))
        children.Next()


def _counting(monkeypatch):
    """How many times OCCT is asked to integrate a solid's volume."""
    calls = []
    integrated = shape_measure._integrated

    def counted(solid):
        calls.append(solid)
        return integrated(solid)

    monkeypatch.setattr(shape_measure, "_integrated", counted)
    return calls


def test_a_compound_and_then_its_children_integrate_each_solid_once(monkeypatch):
    """What an encoder does with a script's compound and the components it holds."""
    calls = _counting(monkeypatch)
    solids = _distinct_solids()
    measurer = shape_measure.Measurer()

    measurer.measurements(_compound(*solids))
    for solid in solids:
        measurer.measurements(solid)

    assert len(calls) == len(solids)


def test_one_solid_placed_many_times_is_integrated_once(monkeypatch):
    calls = _counting(monkeypatch)
    shape = _compounds()["one solid placed six times"]

    shape_measure.measurements(shape)

    assert len(calls) == 1


def test_a_solid_turned_inside_out_is_not_the_same_solid(monkeypatch):
    """Orientation is part of what a solid is: its volume is negative."""
    calls = _counting(monkeypatch)
    solid = _distinct_solids()[0]

    measured = shape_measure.measurements(_compound(solid, solid.Reversed()))

    assert len(calls) == 2
    assert measured["volume"] == pytest.approx(0.0, abs=1e-6)
    assert "centroid" not in measured


def test_only_a_rigid_motion_moves_numbers():
    """A scale or a mirror changes what there is to integrate, so it is integrated again."""
    measured = (6000.0, [5.0, 10.0, 15.0], [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]])
    scale = gp_Trsf()
    scale.SetScale(gp_Pnt(1.0, 2.0, 3.0), 2.0)
    mirror = gp_Trsf()
    mirror.SetMirror(gp_Pnt(0.0, 0.0, 0.0))
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(0.0, 0.0, 1.0)), math.radians(90.0))

    assert shape_measure._moved(measured, scale) is None
    assert shape_measure._moved(measured, mirror) is None
    volume, centre, tensor = shape_measure._moved(measured, turn)
    assert volume == 6000.0
    assert centre == pytest.approx([-10.0, 5.0, 15.0])
    assert tensor == [pytest.approx(row, abs=1e-12) for row in ([2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 3.0])]


def test_one_measurer_answers_for_several_shapes_sharing_a_solid(monkeypatch):
    """What 'ocp_serialize.encode()' does for every shape in one document."""
    calls = _counting(monkeypatch)
    solid = _distinct_solids()[2]
    measurer = shape_measure.Measurer()

    first = measurer.measurements(_compound(solid, _placed(solid, (10.0, 0.0, 0.0))))
    second = measurer.measurements(_placed(solid, (0.0, 30.0, 0.0), (1.0, 0.0, 0.0), 45.0))

    assert len(calls) == 1
    assert first["solids"] == 2
    assert second["volume"] == pytest.approx(4.0 / 3.0 * math.pi * 7.5**3, rel=1e-6)


def test_a_null_shape_measures_as_holding_nothing():
    """As it did measured whole - and without asking OCCT anything, which would crash."""
    from OCP.TopoDS import TopoDS_Shape

    nothing = {"bbox": None, "volume": None, "solids": 0, "freeShells": 0}
    assert shape_measure.Measurer().measurements(TopoDS_Shape()) == nothing
    assert shape_measure.measurements_or_none(TopoDS_Shape()) == nothing
