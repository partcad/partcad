#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The interference wrapper, asked in-process the way 'test_wrapper_solidify.py' asks its neighbour.

'test_assembly_geometry_tests.py' stubs the wrapper out. What is checked here is
the part of it that only the wrapper can get right: that the pairs a joint
already accounts for are never measured, and that every other pair still is.
"""

import os
import sys

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

import partcad as pc
from partcad.test import interference as core_rule

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_interference  # noqa: E402


def _box(x):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0.0, 0.0), 10.0, 10.0, 10.0).Shape()


def _request(expected=()):
    # Three 10 mm cubes in a row, each sharing a 2 mm slab - 200 mm^3 - with
    # the next: 'pin' with 'beam', and 'beam' with 'cover'.
    tree = ocp_serialize.encode_assembly(
        [
            ocp_serialize.encode_shape(_box(0.0), name="//pkg:a", label="pin"),
            ocp_serialize.encode_shape(_box(8.0), name="//pkg:b", label="beam"),
            ocp_serialize.encode_shape(_box(16.0), name="//pkg:c", label="cover"),
        ],
        name="asm",
    )
    return {"assembly_json": ocp_serialize.dumps(tree), "expected": [list(pair) for pair in expected]}


def _counting_common(monkeypatch):
    asked = []
    real = wrapper_interference.BRepAlgoAPI_Common

    def common(a, b):
        asked.append((a, b))
        return real(a, b)

    monkeypatch.setattr(wrapper_interference, "BRepAlgoAPI_Common", common)
    return asked


def test_every_overlap_is_measured_when_no_joint_accounts_for_one(monkeypatch):
    asked = _counting_common(monkeypatch)

    result = wrapper_interference.process(None, _request())

    assert result["success"]
    assert sorted((o["a"], o["b"]) for o in result["overlaps"]) == [("beam", "cover"), ("pin", "beam")]
    assert all(abs(o["volume"] - 200.0) < 1e-6 for o in result["overlaps"])
    assert len(asked) == 2 and result["expected"] == 0


def test_a_pair_the_joint_accounts_for_is_not_measured_at_all(monkeypatch):
    """A seated pin is the slowest boolean an assembly has, and its answer is thrown away."""
    asked = _counting_common(monkeypatch)

    # Named the other way round from the order the tree lists them in.
    result = wrapper_interference.process(None, _request(expected=[("beam", "pin")]))

    assert result["success"]
    assert [(o["a"], o["b"]) for o in result["overlaps"]] == [("beam", "cover")]
    assert len(asked) == 1 and result["expected"] == 1
    assert result["indeterminate"] == []


def test_a_pattern_names_whole_path_segments():
    expected = [("frame/beam", "pin")]
    assert wrapper_interference._is_expected("car/frame/beam", "car/pin", expected)
    assert not wrapper_interference._is_expected("car/subframe/beam", "car/pin", expected)
    assert not wrapper_interference._is_expected("car/frame/crossbeam", "car/pin", expected)


def test_the_wrapper_and_the_test_name_pairs_by_the_same_rule():
    """Two copies of one rule, since the sandbox cannot import PartCAD; held together here."""
    cases = [
        ("pin", "pin"),
        ("a/pin", "pin"),
        ("a/b/pin", "b/pin"),
        ("a/spin", "pin"),
        ("pin/a", "pin"),
        ("ab/pin", "b/pin"),
    ]
    for name, pattern in cases:
        assert wrapper_interference._matches(name, pattern) == core_rule._matches(name, pattern), (name, pattern)


def test_a_part_that_is_not_a_solid_is_not_checked_rather_than_checked_wrongly(monkeypatch):
    """The guard is the definition every part is built against, not a volume sign.

    An open shell's volume integral is positive as often as not, and a boolean
    against it answers with whatever it likes.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Shell

    asked = _counting_common(monkeypatch)
    builder = BRep_Builder()
    open_box = TopoDS_Shell()
    builder.MakeShell(open_box)
    faces = TopExp_Explorer(_box(8.0), TopAbs_FACE)
    faces.Next()  # leave one face off: an open box over 'pin'
    while faces.More():
        builder.Add(open_box, faces.Current())
        faces.Next()
    tree = ocp_serialize.encode_assembly(
        [
            ocp_serialize.encode_shape(_box(0.0), name="//pkg:a", label="pin"),
            ocp_serialize.encode_shape(open_box, name="//pkg:b", label="shell"),
        ],
        name="asm",
    )
    result = wrapper_interference.process(None, {"assembly_json": ocp_serialize.dumps(tree)})

    assert result["success"]
    assert result["unchecked"] == ["shell"]
    assert result["overlaps"] == [] and asked == []
