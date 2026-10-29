#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A script's components are references into its compound, not a second copy of it.

'wrapper_common.combine()' hands back a compound and the shapes it was made of,
which the compound holds. Encoded as they stood, the geometry was written,
measured, sent and cached twice; 'ocp_serialize.encode_combined()' writes it
once and makes each component a node naming the compound's payload and which
child of it it is (KEY_CHILD). These hold what that must not change - every
component decodes to the geometry it was, measures what it measured, and keeps
its place in the nesting - and what it is for: the answer carries the geometry
once.
"""

import json
import os
import sys

import pytest

import partcad as pc

# 'partcad' before OCP: see the note in test_ocp_serialize_sharing.
# isort: split

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Iterator

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import shape_measure  # noqa: E402
import wrapper_common  # noqa: E402


def _moved(shape, x=0.0, y=0.0, z=0.0):
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(x, y, z))
    return shape.Moved(TopLoc_Location(trsf))


def _solids():
    return [
        _moved(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Solid(), x=100.0),
        _moved(BRepPrimAPI_MakeCylinder(4.0, 25.0).Solid(), y=50.0),
        _moved(BRepPrimAPI_MakeSphere(7.5).Solid(), z=-40.0),
    ]


def _encoded(shapes, kind="part"):
    compound, components = wrapper_common.combine(shapes, kind)
    return ocp_serialize.encode_combined(compound, components, name="//pkg:part", label="part")


def _leaves(components):
    for component in components:
        if isinstance(component, list):
            yield from _leaves(component)
        else:
            yield component


def test_every_component_the_compound_holds_names_its_payload_and_its_place():
    shape, components = _encoded(_solids())

    assert [component[ocp_serialize.KEY_CHILD] for component in components] == [0, 1, 2]
    for component in components:
        # The very string: the payload table then carries it once.
        assert component[ocp_serialize.KEY_BREP] is shape[ocp_serialize.KEY_BREP]
        assert (component["name"], component["label"]) == ("//pkg:part", "part")


def test_each_component_decodes_to_the_child_it_is():
    solids = _solids()
    shape, components = _encoded(solids)

    answer = ocp_serialize.loads(ocp_serialize.dumps({"shape": shape, "components": components}, share=True))

    children = []
    iterator = TopoDS_Iterator(answer["shape"])
    while iterator.More():
        children.append(iterator.Value())
        iterator.Next()
    for component, child, solid in zip(answer["components"], children, solids):
        # One decoding: the component is the compound's own child, not a copy.
        assert component.IsEqual(child)
        assert component.ShapeType() == solid.ShapeType()
        assert shape_measure.bbox(component) == pytest.approx(shape_measure.bbox(solid))


def test_each_component_carries_what_it_measures_on_its_own():
    solids = _solids()
    _shape, components = _encoded(solids)

    for component, solid in zip(components, solids):
        measured = component[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_MEASUREMENTS]
        expected = shape_measure.measurements(solid)
        assert measured["bbox"] == expected["bbox"]
        assert measured["volume"] == pytest.approx(expected["volume"], rel=1e-12)
        assert measured["centroid"] == pytest.approx(expected["centroid"], rel=1e-9)


def _payloads(document):
    """How much BREP a serialized answer carries: its payloads' total length, in its table or on its nodes."""

    def walk(obj):
        if isinstance(obj, dict):
            return sum(
                len(value) if key == ocp_serialize.KEY_BREP else walk(value)
                for key, value in obj.items()
                if key != ocp_serialize.KEY_BREPS
            )
        if isinstance(obj, list):
            return sum(walk(item) for item in obj)
        return 0

    parsed = json.loads(document)
    return walk(parsed) + sum(len(payload) for payload in parsed.get(ocp_serialize.KEY_BREPS, {}).values())


def test_the_answer_carries_the_geometry_once():
    solids = _solids()
    shape, components = _encoded(solids)
    once = ocp_serialize.dumps({"shape": shape, "components": components}, share=True)

    compound, raw = wrapper_common.combine(solids, "part")
    twice = ocp_serialize.dumps({"shape": compound, "components": raw}, share=True)

    payload = len(shape[ocp_serialize.KEY_BREP])
    assert _payloads(once) == payload
    # Each component a payload of its own, beside the compound holding them all.
    assert _payloads(twice) > 1.8 * payload


def test_the_nesting_a_script_returned_is_kept():
    solids = _solids()
    shape, components = _encoded([solids[0], [solids[1], [solids[2]]]])

    assert components[0][ocp_serialize.KEY_CHILD] == 0
    assert components[1][0][ocp_serialize.KEY_CHILD] == 1
    assert components[1][1][0][ocp_serialize.KEY_CHILD] == 2

    decoded = ocp_serialize.decode({"shape": shape, "components": components})["components"]
    assert decoded[1][1][0].ShapeType() == solids[2].ShapeType()


def test_a_component_the_compound_leaves_out_is_a_shape_of_its_own():
    """A face beside a part's solids is a component, and no part of the part's compound."""
    solids = _solids()
    face = TopExp_Explorer(solids[0], TopAbs_FACE).Current()

    shape, components = _encoded([solids[1], face])

    assert ocp_serialize.KEY_CHILD in components[0]
    assert ocp_serialize.KEY_CHILD not in components[1]
    assert components[1][ocp_serialize.KEY_BREP] != shape[ocp_serialize.KEY_BREP]
    assert ocp_serialize.decode_shape(components[1]).ShapeType() == face.ShapeType()


def test_a_sketch_s_faces_are_children_of_its_compound_too():
    faces = []
    explorer = TopExp_Explorer(_solids()[0], TopAbs_FACE)
    while explorer.More():
        faces.append(explorer.Current())
        explorer.Next()

    _shape, components = _encoded([faces], kind="sketch")

    assert [component[ocp_serialize.KEY_CHILD] for component in components[0]] == list(range(6))


def test_decode_tree_gives_a_component_its_child():
    solids = _solids()
    shape, components = _encoded(solids)

    placed, node = ocp_serialize.decode_tree(components[2])

    assert node[ocp_serialize.KEY_SHAPE].ShapeType() == solids[2].ShapeType()
    assert shape_measure.bbox(placed) == pytest.approx(shape_measure.bbox(solids[2]))


def test_a_child_the_payload_does_not_have_is_an_error():
    shape, _components = _encoded(_solids())

    for child in (3, -1, "0", True):
        with pytest.raises(ValueError):
            ocp_serialize.decode_shape(dict(shape, **{ocp_serialize.KEY_CHILD: child}))


def test_a_decoding_shared_across_documents_holds_shapes_and_nothing_else():
    """A batch of outputs decodes every request of one call into one set of shapes, and looks over them all.

    'wrapper_export.carries_mesh' asks each of them whether it arrived with a
    mesh on it; anything in there that is not a shape fails that, and with it
    every file the batch was writing together.
    """
    from OCP.TopoDS import TopoDS_Shape

    shape, components = _encoded(_solids())
    shared = {}

    first = ocp_serialize.decode({"components": components}, shared)["components"]
    second = ocp_serialize.decode({"shape": shape, "components": components[1:]}, shared)

    assert shared and all(isinstance(value, TopoDS_Shape) for value in shared.values())
    # The payload read once for both documents, and its children taken out of it once.
    assert len([key for key in shared if isinstance(key, (str, bytes))]) == 1
    assert [component.IsEqual(other) for component, other in zip(first[1:], second["components"])] == [True, True]


def test_what_is_encoded_travels_as_json():
    shape, components = _encoded(_solids())

    assert json.loads(json.dumps(components))[0][ocp_serialize.KEY_CHILD] == 0
    assert list(_leaves(components))


# What a part factory asks of the wrapper building a part (see 'Shape.finish_request').
_VALIDATE = {"validate": {"solidify": True}}
_MOVE = [[0.0, 0.0, 1000.0], [0.0, 0.0, 1.0], 0.0]


def _finishing(monkeypatch, finish):
    """The request this test's wrapper answers asks for 'finish' (see 'wrapper_common.finished')."""
    monkeypatch.setattr(wrapper_common, "_request_finish", finish)
    monkeypatch.setattr(wrapper_common, "_request_name", "//pkg:part")
    monkeypatch.setattr(wrapper_common, "_request_label", "part")


def test_a_finished_part_s_components_refer_into_the_compound_it_was_finished_into(monkeypatch):
    """What the core is handed is the finished compound, so that is what the components are pieces of."""
    _finishing(monkeypatch, _VALIDATE)
    compound, raw = wrapper_common.combine(_solids(), "part")

    shape, components = wrapper_common.encode_combined(compound, raw, finish=True)

    metadata = shape[ocp_serialize.KEY_METADATA]
    assert metadata[ocp_serialize.METADATA_FINISHED] == {
        ocp_serialize.FINISHED_VALIDATED: {"solidify": True, "problems": []}
    }
    assert metadata[ocp_serialize.METADATA_MEASUREMENTS]["solids"] == 3
    assert [component[ocp_serialize.KEY_CHILD] for component in components] == [0, 1, 2]
    for component in components:
        assert component[ocp_serialize.KEY_BREP] is shape[ocp_serialize.KEY_BREP]
        # The claim is about the part, and the core takes it off the part alone.
        assert set(component[ocp_serialize.KEY_METADATA]) == {ocp_serialize.METADATA_MEASUREMENTS}


def test_a_moved_part_s_components_stay_where_the_script_left_them(monkeypatch):
    """Moving a part copies it, so it holds none of them - and the core has never moved them with it."""
    _finishing(monkeypatch, dict(_VALIDATE, offset=_MOVE))
    solids = _solids()
    compound, raw = wrapper_common.combine(solids, "part")

    shape, components = wrapper_common.encode_combined(compound, raw, finish=True)

    assert shape[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_FINISHED]["offset"] == _MOVE
    moved = shape_measure.bbox(ocp_serialize.decode_shape(shape))
    assert moved[2] == pytest.approx(shape_measure.bbox(compound)[2] + 1000.0)
    for component, solid in zip(components, solids):
        assert ocp_serialize.KEY_CHILD not in component
        assert shape_measure.bbox(ocp_serialize.decode_shape(component)) == pytest.approx(shape_measure.bbox(solid))


def test_a_part_that_asked_for_nothing_is_not_finished(monkeypatch):
    """A sketch, a failed build: the compound as 'combine()' made it, claiming nothing."""
    _finishing(monkeypatch, _VALIDATE)
    compound, raw = wrapper_common.combine(_solids(), "part")

    shape, components = wrapper_common.encode_combined(compound, raw, finish=False)

    assert ocp_serialize.METADATA_FINISHED not in shape[ocp_serialize.KEY_METADATA]
    assert [component[ocp_serialize.KEY_CHILD] for component in components] == [0, 1, 2]
