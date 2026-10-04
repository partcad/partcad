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


def test_a_pattern_names_a_subtree_by_its_exact_path():
    expected = [("frame/beam", "pin")]
    assert wrapper_interference._is_expected("frame/beam", "pin", expected)
    assert wrapper_interference._is_expected("frame/beam/rib", "pin", expected)
    assert not wrapper_interference._is_expected("subframe/beam", "pin", expected)
    assert not wrapper_interference._is_expected("frame/crossbeam", "pin", expected)
    assert not wrapper_interference._is_expected("car/frame/beam", "car/pin", expected)


def test_the_wrapper_and_the_test_name_pairs_by_the_same_rule():
    """Two copies of one rule, since the sandbox cannot import PartCAD; held together here."""
    cases = [
        ("pin", "pin"),
        ("a/pin", "a"),
        ("a/b/pin", "a/b"),
        ("a/pin", "pin"),
        ("ab/pin", "a"),
        ("pin/a", "pin"),
        ("spin", "pin"),
    ]
    for name, pattern in cases:
        assert wrapper_interference._within(name, pattern) == core_rule._within(name, pattern), (name, pattern)


def _group(label, *children, at=None):
    """An assembly node of the tree, placed 'at' an x offset if given."""
    node = ocp_serialize.encode_assembly(list(children), name="//pkg:" + label, label=label)
    if at is not None:
        node["location"] = [[at, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    return node


def _part(label, x):
    return ocp_serialize.encode_shape(_box(x), name="//pkg:" + label, label=label)


def _check(tree, **request):
    request["assembly_json"] = ocp_serialize.dumps(ocp_serialize.encode_assembly(tree, name="asm"))
    return wrapper_interference.process(None, request)


def test_a_pair_of_subtrees_the_joints_account_for_is_skipped_whole(monkeypatch):
    """Kept as the pair of subtrees the joint declared: nothing under either is measured against the other."""
    asked = _counting_common(monkeypatch)
    battery = _group("battery", _part("box", 0.0), _part("pin", 8.0))
    frame = _group("frame", _part("rail", 8.0), _part("post", 16.0))
    result = _check([battery, frame], expected=[["frame", "battery"]])
    # battery/pin and frame/rail coincide, battery/box meets frame/rail: all excused.
    assert [(o["a"], o["b"]) for o in result["overlaps"] if o["a"].split("/")[0] != o["b"].split("/")[0]] == []
    assert result["expected"] == 1
    # What is inside each subtree is still measured: box/pin, rail/post.
    assert sorted((o["a"], o["b"]) for o in result["overlaps"]) == [
        ("battery/box", "battery/pin"),
        ("frame/rail", "frame/post"),
    ]
    assert len(asked) == 2


def test_the_inside_of_a_subassembly_with_a_verdict_of_its_own_is_not_measured(monkeypatch):
    asked = _counting_common(monkeypatch)
    piece = _group("piece", _part("a", 0.0), _part("b", 8.0))
    result = _check([piece, _part("neighbour", 16.0)], opaque=["piece"])
    # piece/a-piece/b overlap too, but that is the piece's own business.
    assert [(o["a"], o["b"]) for o in result["overlaps"]] == [("piece/b", "neighbour")]
    assert len(asked) == 1


def test_subtrees_whose_boxes_miss_are_done_with_in_one_test(monkeypatch):
    asked = _counting_common(monkeypatch)
    near = _group("near", _part("a", 0.0), _part("b", 20.0))
    far = _group("far", _part("c", 0.0), _part("d", 20.0), at=1000.0)
    result = _check([near, far])
    assert result["overlaps"] == [] and result["candidates"] == 0 and asked == []


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
