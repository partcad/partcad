#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tolerance wrapper, asked in-process: which faces and edges a STEP file's GD&T covers.

The fixture is 'data/qual_tolerance/bored_block.step': a 20 x 10 x 5 mm block
with a 4 mm bore, whose GD&T is a flatness on the top face and a cylindricity on
the bore -- two faces of seven.
"""

import os
import sys

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_tolerance  # noqa: E402

STEP = os.path.join(os.path.dirname(__file__), "data", "qual_tolerance", "bored_block.step")


def _block():
    box = BRepPrimAPI_MakeBox(20.0, 10.0, 5.0).Shape()
    bore = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10.0, 5.0, -1.0), gp_Dir(0.0, 0.0, 1.0)), 2.0, 10.0).Shape()
    return BRepAlgoAPI_Cut(box, bore).Shape()


def test_with_no_file_nothing_is_toleranced():
    faces = wrapper_tolerance.untoleranced({"shape": _block(), "kind": "face"})
    assert (faces["total"], faces["toleranced"], faces["untoleranced"]) == (7, 0, 7)
    assert faces["highlight"] is not None
    # The bore's seam is not an edge of anything anybody makes.
    edges = wrapper_tolerance.untoleranced({"shape": _block(), "kind": "edge"})
    assert (edges["total"], edges["untoleranced"]) == (14, 14)
    assert edges["tubes"] == 14


def test_the_files_gdt_covers_the_faces_it_refers_to():
    references, whole = wrapper_tolerance.referenced_shapes(STEP)
    assert len(references) == 2 and whole is not None
    faces = wrapper_tolerance.untoleranced({"shape": _block(), "kind": "face", "step": STEP})
    assert (faces["total"], faces["toleranced"], faces["untoleranced"]) == (7, 2, 5)
    assert faces["described"][0]["type"].endswith("Plane")


def test_an_edge_is_covered_by_both_of_its_faces_being_covered():
    edges = wrapper_tolerance.untoleranced({"shape": _block(), "kind": "edge", "step": STEP})
    # The rim of the bore on the top face, between the two faces the file
    # tolerances; every other edge has a face nothing tolerances beside it.
    assert (edges["toleranced"], edges["untoleranced"]) == (1, 13)


def test_a_part_moved_as_a_whole_still_matches_its_file():
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(100.0, 50.0, 7.0))
    moved = BRepBuilderAPI_Transform(_block(), move, True).Shape()
    faces = wrapper_tolerance.untoleranced({"shape": moved, "kind": "face", "step": STEP})
    assert faces["toleranced"] == 2


def test_small_faces_are_left_out_when_asked():
    faces = wrapper_tolerance.untoleranced({"shape": _block(), "kind": "face", "step": STEP, "minSize": 100.0})
    # The two big planes are left: the top one is toleranced, the bottom is not.
    assert (faces["untoleranced"], faces["smaller"]) == (1, 4)
