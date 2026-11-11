#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The defects wrapper, asked in-process: which faces and edges of a shape are badly made, and only those.

The shapes are made here with OCCT: a box, which is sound; the same box with a
face left out, which has four free edges; a block fused with one half a
micrometre wider, which leaves slivers; and a shape every face of which is a
sliver, which the wrapper counts but does not draw. And then the same check in
shards, which has to give the same answer as one run.
"""

import io
import json
import os
import sys

import pytest
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shell, TopoDS_Solid

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_defects  # noqa: E402


def _open_box():
    """A 20 x 10 x 5 mm box with its first face left out, made into a solid all the same."""
    box = BRepPrimAPI_MakeBox(20.0, 10.0, 5.0).Shape()
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    explorer = TopExp_Explorer(box, TopAbs_FACE)
    first = True
    while explorer.More():
        if not first:
            builder.Add(shell, explorer.Current())
        first = False
        explorer.Next()
    solid = TopoDS_Solid()
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return solid


def _slivered():
    block = BRepPrimAPI_MakeBox(20.0, 10.0, 10.0).Shape()
    wider = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 20.0, 10.0005, 5.0).Shape()
    fuse = BRepAlgoAPI_Fuse(block, wider)
    fuse.Build()
    return fuse.Shape()


def test_a_sound_box_has_nothing_to_show():
    found = wrapper_defects.find({"shape": BRepPrimAPI_MakeBox(20.0, 10.0, 5.0).Shape()})
    assert found["valid"] is True
    assert (found["defective_faces"], found["defective_edges"]) == (0, 0)
    assert found["pieces"] == [] and found["described"] == []


def test_the_edges_around_a_hole_are_free_and_drawn_as_tubes():
    found = wrapper_defects.find({"shape": _open_box()})
    assert found["valid"] is False
    assert (found["defective_faces"], found["defective_edges"], found["free"]) == (0, 4, 4)
    assert found["whole"] == ["NotClosed"]
    assert [piece["kind"] for piece in found["pieces"]] == ["edge"]
    assert found["tubes"] == 4
    # Each where it is: on the face that was left out, x = 0.
    assert all(item["problems"] == ["free"] and abs(item["center"][0]) < 1e-9 for item in found["described"])


def test_slivers_are_the_pieces_thinner_than_the_threshold_and_only_those():
    found = wrapper_defects.find({"shape": _slivered()})
    assert found["valid"] is True
    assert (found["defective_faces"], found["defective_edges"], found["slivers"]) == (4, 4, 8)
    assert found["faces"] == 14 and not found["whole_faces"]
    assert sorted(piece["kind"] for piece in found["pieces"]) == ["edge", "face"]
    # Below the slivers' size, nothing is one.
    assert wrapper_defects.find({"shape": _slivered(), "minLength": 1e-4})["slivers"] == 0


def test_a_shape_every_face_of_which_is_defective_is_counted_and_not_drawn():
    # A rod half a millimetre square: held to a millimetre, every face of it is
    # narrower than that, and its long edges are not shorter.
    found = wrapper_defects.find({"shape": BRepPrimAPI_MakeBox(20.0, 0.5, 0.5).Shape(), "minLength": 1.0})
    assert found["defective_faces"] == found["faces"] == 6
    assert found["whole_faces"] is True
    assert all(piece["kind"] != "face" for piece in found["pieces"])
    assert not found["whole_edges"]
    assert [piece["kind"] for piece in found["pieces"]] == ["edge"]


# Sharded, the check gives the answer it gives in one run, exactly. The shapes
# are the ones above and some with faults OCCT finds on a piece: an edge whose
# curve is moved off both faces it bounds (the faces then cannot be oriented), a
# face whose wire crosses itself, a vertex moved off its edges (which makes the
# shape invalid with no face or edge at fault), and a wire lying outside every
# face.


def _compound(*shapes):
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def _bent_edge():
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    edge = TopoDS.Edge_s(TopExp_Explorer(box, TopAbs_EDGE).Current())
    curve = BRep_Tool.Curve_s(edge, 0.0, 1.0)
    moved = gp_Trsf()
    moved.SetTranslation(gp_Vec(0.5, 0.5, 0.0))
    BRep_Builder().UpdateEdge(edge, curve.Transformed(moved), 1e-7)
    return box


def _bowtie():
    wire = BRepBuilderAPI_MakePolygon(
        gp_Pnt(0.0, 0.0, 30.0), gp_Pnt(10.0, 10.0, 30.0), gp_Pnt(10.0, 0.0, 30.0), gp_Pnt(0.0, 10.0, 30.0), True
    ).Wire()
    return BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0.0, 0.0, 30.0), gp_Dir(0.0, 0.0, 1.0)), wire).Face()


def _moved_vertex():
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    vertex = TopoDS.Vertex_s(TopExp_Explorer(box, TopAbs_VERTEX).Current())
    BRep_Builder().UpdateVertex(vertex, gp_Pnt(0.5, 0.3, 0.2), 1e-7)
    return box


def _loose_wire():
    return BRepBuilderAPI_MakePolygon(gp_Pnt(0.0, 0.0, 50.0), gp_Pnt(1.0, 0.0, 50.0), gp_Pnt(1.0, 1.0, 50.0)).Wire()


SHAPES = {
    "sound": lambda: BRepPrimAPI_MakeBox(20.0, 10.0, 5.0).Shape(),
    "open_box": _open_box,
    "slivered": _slivered,
    "bent_edge": _bent_edge,
    "moved_vertex": _moved_vertex,
    "bowtie_and_open_box": lambda: _compound(BRepPrimAPI_MakeBox(20.0, 10.0, 5.0).Shape(), _bowtie(), _open_box()),
    "many": lambda: _compound(_bent_edge(), _slivered(), _open_box(), _loose_wire()),
}


def _brep(shape) -> str:
    stream = io.BytesIO()
    BRepTools.Write_s(shape, stream)
    return stream.getvalue().decode()


def _comparable(found):
    """'found', with the geometry of each piece as the BREP text OCCT writes for it."""
    found = dict(found)
    found["pieces"] = [(piece["kind"], _brep(piece["shape"])) for piece in found["pieces"]]
    return found


def _sharded(shape, count, min_length=1e-3):
    """What 'count' shards answer, each as it travels (JSON), put together the way the core has it put together."""
    shards = [
        json.loads(json.dumps(wrapper_defects.examine(shape, min_length, index, count))) for index in range(count)
    ]
    request = {"minLength": min_length, "shards": list(reversed(shards))}
    if any(found["face_problems"] or found["edge_problems"] for found in shards):
        request["shape"] = shape
    return wrapper_defects.answer(request)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_sharded_the_answer_is_the_same_to_the_byte(name):
    shape = SHAPES[name]()
    whole = _comparable(wrapper_defects.find({"shape": shape}))
    faces = whole["faces"]
    # Two and three shards; and more shards than faces, so that every face is
    # in a shard of its own and some shards have none.
    for count in (2, 3, faces + 3):
        assert _comparable(_sharded(shape, count)) == whole, count


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_wherever_the_runs_of_edges_are_cut_the_answer_is_the_same(name, monkeypatch):
    # The edges are cut into runs where the faces are, so that an edge is
    # mostly checked by the shard of the faces it bounds; cut evenly instead,
    # paying no attention to the faces, most edges are checked by a shard that
    # has to be handed the faces they bound -- the boundary between a face and
    # its edges falling everywhere.
    deal = wrapper_defects._Pieces._deal

    def even(self, edges, count):
        shards, _ = deal(self, edges, count)
        return shards, [1 + index * edges // count for index in range(count)] + [edges + 1]

    monkeypatch.setattr(wrapper_defects._Pieces, "_deal", even)
    shape = SHAPES[name]()
    whole = _comparable(wrapper_defects.find({"shape": shape}))
    for count in (2, 3, whole["faces"] + 3):
        assert _comparable(_sharded(shape, count)) == whole, count


def test_the_fixtures_have_what_the_comparison_is_meant_to_cover():
    found = {name: wrapper_defects.find({"shape": make()}) for name, make in SHAPES.items()}
    problems = {
        name: sorted({problem for item in result["described"] for problem in item["problems"]})
        for name, result in found.items()
    }
    assert problems["open_box"] == ["free"] and found["open_box"]["whole"] == ["NotClosed"]
    assert problems["slivered"] == ["sliver"]
    assert "InvalidCurveOnSurface" in problems["bent_edge"] and "UnorientableShape" in problems["bent_edge"]
    # The bowtie: a face OCCT finds fault with, on its own.
    assert any(
        item["kind"] == "face" and set(item["problems"]) - {"free", "sliver"}
        for item in found["bowtie_and_open_box"]["described"]
    )
    # Invalid, and nothing to point at: what makes it so is a vertex.
    assert found["moved_vertex"]["valid"] is False and found["moved_vertex"]["described"] == []


def test_an_edge_can_be_checked_in_another_shard_than_the_faces_it_bounds():
    # The bent edge is at fault in each of the two faces it bounds. Dealt one
    # face to a shard, those faces are in two shards, and the edge's run of
    # edges -- cut where the faces are -- puts it with at most one of them: so
    # its shard is handed the other face to check it against, and still finds
    # what one run finds.
    shape = _bent_edge()
    whole = wrapper_defects.find({"shape": shape})
    (edge,) = [item for item in whole["described"] if item["kind"] == "edge"]
    faces = [item["index"] - 1 for item in whole["described"] if item["kind"] == "face"]
    count = whole["faces"]
    kept = 0
    for index in range(count):
        pieces = wrapper_defects._Pieces(shape, index, count)
        if kept <= edge["index"] - 1 < kept + len(pieces.edges):
            owner, bounds = index, pieces.faces_of[edge["index"] - 1 - kept]
            shards = pieces.face_shard
        kept += len(pieces.edges)
    assert sorted(bounds) == sorted(faces)
    assert len({shards[face] for face in faces}) == 2
    assert any(shards[face] != owner for face in faces)
    assert _comparable(_sharded(shape, count)) == _comparable(whole)
