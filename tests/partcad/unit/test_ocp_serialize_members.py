#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""'ocp_serialize.members': what an OCCT list holds, read without iterating the list from Python.

Iterating any OCCT collection from Python costs about 200 microseconds before
its first element in the OCP PartCAD runs on, and the wrappers read a list per
edge or per face -- the faces an edge bounds, the solids a face is in. So a list
is read element by element instead, and it has to come out exactly as iterating
it would: the same elements, in the same order, whatever its length and kind.
"""

import os
import sys

import pytest
from OCP.BRepCheck import BRepCheck_ListOfStatus, BRepCheck_Status
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_ListOfShape

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _faces(count):
    """'count' faces, each a different one, in a list of OCCT's."""
    listed = TopTools_ListOfShape()
    for index in range(count):
        box = BRepPrimAPI_MakeBox(1.0 + index, 1.0, 1.0).Shape()
        found = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(box, TopAbs_EDGE, TopAbs_FACE, found)
        listed.Append(found.FindFromIndex(1).First())
    return listed


# Every way the list is read: empty, by 'First' and 'Last', taken apart from a
# copy, and -- from 'ocp_serialize._ITERATE_FROM' up -- iterated.
@pytest.mark.parametrize("count", [0, 1, 2, 3, 17, ocp_serialize._ITERATE_FROM - 1, ocp_serialize._ITERATE_FROM])
def test_a_list_of_shapes_comes_out_as_iterating_it_would(count):
    listed = _faces(count)
    found = ocp_serialize.members(listed)
    expected = list(listed)
    assert len(found) == len(expected) == count
    assert all(a.IsEqual(b) for a, b in zip(found, expected))
    # Read, not consumed: the list still holds what it held.
    assert listed.Size() == count


def test_a_list_of_statuses_comes_out_as_iterating_it_would():
    statuses = BRepCheck_ListOfStatus()
    for status in (
        BRepCheck_Status.BRepCheck_InvalidCurveOnSurface,
        BRepCheck_Status.BRepCheck_InvalidSameParameterFlag,
        BRepCheck_Status.BRepCheck_UnorientableShape,
    ):
        statuses.Append(status)
    assert ocp_serialize.members(statuses) == list(statuses)


def test_what_an_edge_bounds_is_its_two_faces():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    found = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(box, TopAbs_EDGE, TopAbs_FACE, found)
    for index in range(1, found.Extent() + 1):
        faces = ocp_serialize.members(found.FindFromIndex(index))
        assert len(faces) == 2 and not faces[0].IsSame(faces[1])
        assert [face.IsEqual(other) for face, other in zip(faces, list(found.FindFromIndex(index)))] == [True, True]
