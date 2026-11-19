#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which face or edge a comment is about, among the wrappers ('element_refs').

Run here against real OCP solids, in this process: what the sandbox runs is
this module, through 'wrapper_measure' ('anchors' and 'locate'), and the core's
side of it ('measure.element_anchors', 'measure.locate_element') only carries
the shape there and the answer back.
"""

import math
import os
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))

pytest.importorskip("OCP")


def _box(x=10.0, y=20.0, z=30.0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(x, y, z).Shape()


def _cylinder(radius=5.0, height=10.0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    return BRepPrimAPI_MakeCylinder(radius, height).Shape()


def _faces(shape):
    import element_refs

    return element_refs._elements(shape, "face")


def _on(shape, point, tolerance=1e-6):
    """Whether 'point' is on 'shape'."""
    import element_refs

    return element_refs._nearest_on(element_refs._vertex(point), shape)[0] <= tolerance


def test_every_face_and_edge_named_is_anchored_on_itself():
    import element_refs

    box = _box()
    assert element_refs.counts(box) == {"faces": 6, "edges": 12}
    found = element_refs.anchors(box, ["face:1", "face:6", "edge:12", "edge:1", "face:6"])
    assert set(found) == {"face:1", "face:6", "edge:12", "edge:1"}
    for ref, at in found.items():
        element, index = ref.split(":")
        piece = element_refs._elements(box, element)[int(index) - 1]
        assert _on(piece, at), ref


def test_a_curved_face_is_anchored_on_it_and_not_on_its_axis():
    import element_refs

    cylinder = _cylinder()
    side = next(index for index, face in enumerate(_faces(cylinder), 1) if not _flat(face))
    (at,) = element_refs.anchors(cylinder, ["face:%d" % side]).values()
    # The centre of mass of the side of a cylinder is on its axis; a point of
    # the side is a radius away from it.
    assert math.hypot(at[0], at[1]) == pytest.approx(5.0, abs=1e-6)


def _flat(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopoDS import TopoDS

    return BRepAdaptor_Surface(TopoDS.Face_s(face)).GetType() == GeomAbs_Plane


def test_what_the_shape_does_not_have_is_left_out():
    import element_refs

    assert element_refs.anchors(_box(), ["face:7", "edge:13", "base", "vertex:1", None]) == {}


def test_a_click_on_a_face_is_that_face():
    import element_refs

    box = _box()
    # The middle of the top face, which is at z = 30.
    found = element_refs.locate(box, [5.0, 10.0, 30.0], tolerance=0.5)
    assert found["element"] == "face"
    top = element_refs._elements(box, "face")[found["index"] - 1]
    assert _on(top, [5.0, 10.0, 30.0])
    assert found["ref"] == "face:%d" % found["index"]
    assert found["distance"] == pytest.approx(0.0, abs=1e-6)


def test_a_click_beside_an_edge_is_that_edge_and_further_away_the_face():
    import element_refs

    box = _box()
    near = element_refs.locate(box, [0.2, 10.0, 30.0], tolerance=0.5)
    assert near["element"] == "edge"
    edge = element_refs._elements(box, "edge")[near["index"] - 1]
    assert _on(edge, near["at"])
    # The same point with a smaller tolerance - zoomed in - is on the face.
    assert element_refs.locate(box, [0.2, 10.0, 30.0], tolerance=0.1)["element"] == "face"


def test_a_shape_of_lines_alone_answers_its_nearest_edge():
    import element_refs
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt

    line = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0)).Edge()
    found = element_refs.locate(line, [5.0, 3.0, 0.0], tolerance=0.1)
    assert found["ref"] == "edge:1"
    assert found["at"] == pytest.approx([5.0, 0.0, 0.0])


def test_the_measure_wrapper_answers_both_questions():
    import wrapper_measure

    box = _box()
    assert set(wrapper_measure.process({"operation": "anchors", "shape": box, "refs": ["face:2"]})) == {"face:2"}
    located = wrapper_measure.process({"operation": "locate", "shape": box, "point": [5, 10, 30], "tolerance": 0.5})
    assert located["element"] == "face"


def test_the_core_measures_a_shape_in_its_own_frame():
    from partcad import measure, shape_envelope

    placed = {shape_envelope.KEY_BREP: b"...", shape_envelope.KEY_LOCATION: [[1, 2, 3], [0, 0, 1], 90]}
    unplaced = measure._own_frame(placed)
    assert shape_envelope.KEY_LOCATION not in unplaced
    assert shape_envelope.KEY_LOCATION in placed
    plain = {shape_envelope.KEY_BREP: b"..."}
    assert measure._own_frame(plain) is plain
