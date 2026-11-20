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


# --- Selections ----------------------------------------------------------------


def _plate():
    """A 40 x 20 x 5 plate with a hole through it: faces of three kinds, edges of two."""
    pytest.importorskip("build123d")
    import build123d as bd

    return (bd.Box(40, 20, 5) - bd.Cylinder(3, 5)).wrapped


def _is(shape, element, chosen):
    import element_refs

    pieces = element_refs._elements(shape, element)
    return [next(n for n, piece in enumerate(pieces, 1) if piece.IsSame(found)) for found in chosen]


def test_a_build123d_selection_is_what_build123d_selects():
    import element_refs

    plate = _plate()
    (top,) = element_refs.select(plate, "faces().sort_by(Axis.Z)[-1]")
    assert element_refs.anchors(plate, ["faces().sort_by(Axis.Z)[-1]"])["faces().sort_by(Axis.Z)[-1]"][2] == (
        pytest.approx(2.5)
    )
    assert len(element_refs.select(plate, "edges().filter_by(GeomType.CIRCLE)")) == 2
    assert _is(plate, "face", [top]) == [int(element_refs.locate(plate, [10, 5, 2.5], 0.1)["ref"].split(":")[1])]


def test_what_is_more_than_a_selection_is_refused_before_it_is_evaluated():
    import element_refs

    for ref in ('faces().sort_by(__import__("os").system("echo x"))', "faces().__class__", "face:1", "base"):
        with pytest.raises(ValueError):
            element_refs.select(_plate(), ref)


def test_a_selection_that_selects_nothing_is_left_out_like_a_face_the_shape_lacks():
    import element_refs

    assert element_refs.anchors(_plate(), ["faces().filter_by(GeomType.SPHERE)", 'faces(">Q")']) == {}


def test_every_face_and_edge_of_a_build123d_part_gets_a_build123d_selection_of_it_alone():
    import element_refs

    plate = _plate()
    for element in ("face", "edge"):
        for index in range(1, len(element_refs._elements(plate, element)) + 1):
            written = element_refs.selection_for(plate, element, index, "build123d")
            assert written and written.startswith(element + "s()"), (element, index, written)
            assert _is(plate, element, element_refs.select(plate, written)) == [index], written


def test_a_click_on_a_build123d_part_is_named_as_build123d_selects():
    import element_refs

    found = element_refs.locate(_plate(), [10, 5, 2.5], 0.1, style="build123d")
    assert found["ref"] == "faces().sort_by(Axis.Z)[-1]"
    assert found["numbered"] == "face:%d" % found["index"]
    # Without a style it is the number, as it always was.
    assert element_refs.locate(_plate(), [10, 5, 2.5], 0.1)["ref"] == found["numbered"]


def test_a_selection_reads_the_way_a_person_writes_one():
    """An axis before a direction: 'the left edge at the back', not a vector nobody would type."""
    import element_refs

    box = _box(40.0, 20.0, 10.0)
    written = {element_refs.selection_for(box, "edge", n, "build123d") for n in range(1, 13)}
    assert not any("Axis((" in text for text in written), written


def test_every_face_and_edge_of_a_cadquery_part_gets_a_cadquery_selection_of_it_alone():
    import element_refs

    cq = pytest.importorskip("cadquery")
    plate = cq.Workplane().box(40, 20, 5).faces(">Z").workplane().hole(6).val().wrapped
    for element in ("face", "edge"):
        for index in range(1, len(element_refs._elements(plate, element)) + 1):
            written = element_refs.selection_for(plate, element, index, "cadquery")
            assert written and written.startswith(element + 's("'), (element, index, written)
            assert _is(plate, element, element_refs.select(plate, written)) == [index], written


def _example(name):
    import asyncio

    ctx = pc.init("examples")
    part = ctx.get_part(name)
    return ctx, part, asyncio.run(part.get_wrapped(ctx))


def test_a_cadquery_part_is_selected_by_cadquery_in_its_sandbox():
    """End to end: the CadQuery layer is asked for, and CadQuery answers the click and the selection."""
    import asyncio

    from partcad import measure

    ctx, cube, tree = _example("//produce_part_cadquery_primitive:cube")
    found = asyncio.run(measure.locate_element(ctx, tree, [0.0, 0.0, 10.0], 0.01, style="cadquery"))
    assert found["ref"].startswith('faces("'), found
    at = asyncio.run(measure.element_anchors(ctx, tree, [found["ref"], 'edges("|Z")'], cacheable=False))
    assert set(at) == {found["ref"], 'edges("|Z")'}


def test_a_build123d_part_is_selected_by_build123d_in_its_sandbox():
    import asyncio

    from partcad import measure

    ctx, cube, tree = _example("//produce_part_build123d_primitive:cube")
    found = asyncio.run(measure.locate_element(ctx, tree, [0.0, 0.0, 0.0], 1000.0, style="build123d"))
    assert found["ref"].startswith("edges()"), found
    at = asyncio.run(measure.element_anchors(ctx, tree, [found["ref"]], cacheable=False))
    assert set(at) == {found["ref"]}
