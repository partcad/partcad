#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The defects wrapper, asked in-process: which faces and edges of a shape are badly made, and only those.

The shapes are made here with OCCT: a box, which is sound; the same box with a
face left out, which has four free edges; a block fused with one half a
micrometre wider, which leaves slivers; and a shape every face of which is a
sliver, which the wrapper counts but does not draw.
"""

import os
import sys

from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid

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
