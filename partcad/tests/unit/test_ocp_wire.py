#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Round-trip tests for the flat-BREP wire format.

A shape travels as ``{"name", "label", "brep"}`` with ``brep`` the base64 of
``BRepTools.Write_s`` output; an assembly as ``{"name", "label", "assembly":
[...]}``. These tests pin down that a shape survives the round trip numerically -
volume, centre of mass, bounding box - that its ``TopLoc_Location`` is not lost,
that the assembly structure rebuilds into a compound, and that the envelope is
plain single-line JSON rather than base64-wrapped JSON.
"""

import base64
import json
import math
import os
import sys
from io import BytesIO

import pytest

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepTools import BRepTools
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

import partcad  # noqa: F401  (imported for its side effect on sys.path below)

# The wrappers directory is not a package: the main process and the sandboxed
# wrappers both import 'ocp_wire' by bare name off this path.
sys.path.append(os.path.join(os.path.dirname(partcad.__file__), "wrappers"))
import ocp_wire  # noqa: E402


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    com = props.CentreOfMass()
    return props.Mass(), (com.X(), com.Y(), com.Z())


def _surface(shape):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    com = props.CentreOfMass()
    return props.Mass(), (com.X(), com.Y(), com.Z())


def _bbox(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    return box.Get()


def _assert_close(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert math.isclose(a, e, rel_tol=1e-9, abs_tol=1e-9), f"{actual} != {expected}"


def _assert_same_solid(a, b):
    va, ca = _volume(a)
    vb, cb = _volume(b)
    assert math.isclose(va, vb, rel_tol=1e-9)
    _assert_close(ca, cb)
    _assert_close(_bbox(a), _bbox(b))


def _translation(x, y, z):
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(x, y, z))
    return trsf


def _rotation():
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(1.0, 2.0, 3.0), gp_Dir(0.3, 0.5, 0.81)), math.pi / 3.0)
    return trsf


def _box():
    return BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()


def _face():
    return BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), -5.0, 5.0, -7.0, 7.0).Face()


def _compound():
    builder = TopoDS_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, _box())
    builder.Add(compound, BRepPrimAPI_MakeCylinder(3.0, 12.0).Shape())
    return compound


def _located(shape, trsf):
    return shape.Located(TopLoc_Location(trsf))


#
# Shape objects
#


@pytest.mark.parametrize(
    "make_shape",
    [_box, BRepPrimAPI_MakeSphere(7.5).Shape, _compound],
    ids=["solid_box", "solid_sphere", "compound"],
)
def test_shape_object_round_trip(make_shape):
    shape = make_shape()
    obj = ocp_wire.encode_shape(shape, name="//pkg:x", label="x")
    assert set(obj) == {"name", "label", "brep"}
    _assert_same_solid(ocp_wire.decode_shape(obj), shape)


def test_shape_object_carries_name_and_label():
    obj = ocp_wire.encode_shape(_box(), name="//pkg:box", label="my-label")
    assert obj["name"] == "//pkg:box"
    assert obj["label"] == "my-label"


def test_face_round_trip():
    face = _face()
    back = ocp_wire.decode_shape(ocp_wire.encode_shape(face))
    _assert_close(_surface(back)[0:1], _surface(face)[0:1])
    _assert_close(_bbox(back), _bbox(face))


@pytest.mark.parametrize(
    "trsf",
    [_translation(3, -4, 5), _rotation()],
    ids=["translation", "rotation"],
)
def test_location_survives(trsf):
    located = _located(_box(), trsf)
    back = ocp_wire.decode_shape(ocp_wire.encode_shape(located))
    _assert_same_solid(back, located)


def test_brep_field_is_base64_of_breptools_output():
    shape = _box()
    obj = ocp_wire.encode_shape(shape)
    stream = BytesIO()
    BRepTools.Write_s(shape, stream)
    assert base64.b64decode(obj["brep"]) == stream.getvalue()


#
# Assembly objects
#


def test_assembly_object_round_trips_to_compound():
    box = _box()
    cyl = BRepPrimAPI_MakeCylinder(3.0, 12.0).Shape()
    asm = ocp_wire.encode_assembly(
        [ocp_wire.encode_shape(box, name="//p:b", label="b"), ocp_wire.encode_shape(cyl, name="//p:c", label="c")],
        name="//p:asm",
        label="asm",
    )
    assert set(asm) == {"name", "label", "assembly"}
    assert ocp_wire.is_assembly_object(asm)
    compound = ocp_wire.decode_shape(asm)
    want = _volume(box)[0] + _volume(cyl)[0]
    assert math.isclose(_volume(compound)[0], want, rel_tol=1e-9)


def test_nested_sub_assembly_survives_json():
    box = _box()
    sub = ocp_wire.encode_assembly([ocp_wire.encode_shape(box)], name="//p:sub", label="sub")
    top = ocp_wire.encode_assembly([ocp_wire.encode_shape(box), sub], name="//p:top", label="top")
    # round-trip through JSON text, as the cache does
    top = json.loads(json.dumps(top))
    assert ocp_wire.is_assembly_object(top["assembly"][1])
    compound = ocp_wire.decode_shape(top)
    assert math.isclose(_volume(compound)[0], 2 * _volume(box)[0], rel_tol=1e-9)


def test_shape_vs_assembly_discrimination():
    shape_obj = ocp_wire.encode_shape(_box())
    asm_obj = ocp_wire.encode_assembly([shape_obj])
    assert ocp_wire.is_shape_object(shape_obj) and not ocp_wire.is_assembly_object(shape_obj)
    assert ocp_wire.is_assembly_object(asm_obj) and not ocp_wire.is_shape_object(asm_obj)


#
# Envelope
#


def test_envelope_carries_plain_data_unchanged():
    payload = {"success": True, "exception": None, "count": 3, "opts": {"tol": 0.1}, "names": ["a", "b"]}
    assert ocp_wire.deserialize(ocp_wire.serialize(payload)) == payload


def test_envelope_carries_a_shape_under_a_key():
    shape = _box()
    wire = ocp_wire.serialize({"success": True, "exception": None, "shape": shape})
    result = ocp_wire.deserialize(wire)
    assert result["success"] is True and result["exception"] is None
    _assert_same_solid(result["shape"], shape)


def test_envelope_carries_nested_shape_lists():
    shapes = [_box(), None, "ignored", [BRepPrimAPI_MakeCylinder(3.0, 12.0).Shape()]]
    result = ocp_wire.deserialize(ocp_wire.serialize({"shapes": shapes}))["shapes"]
    _assert_same_solid(result[0], _box())
    assert result[1] is None and result[2] == "ignored"
    _assert_same_solid(result[3][0], BRepPrimAPI_MakeCylinder(3.0, 12.0).Shape())


def test_exceptions_become_strings():
    result = ocp_wire.deserialize(ocp_wire.serialize({"exception": ValueError("boom")}))
    assert result["exception"] == "boom"


def test_non_shape_occt_objects_drop_to_none():
    # A TopLoc_Location or gp_Ax1 (a build123d visualization helper) is not
    # geometry; it drops to null, which every consumer already skips.
    result = ocp_wire.deserialize(ocp_wire.serialize({"shapes": [TopLoc_Location(), gp_Ax1(gp_Pnt(), gp_Dir(0, 0, 1))]}))
    assert result["shapes"] == [None, None]


def test_unknown_python_type_is_rejected():
    with pytest.raises(TypeError):
        ocp_wire.serialize({"x": object()})


#
# Wire form
#


def test_serialize_is_plain_single_line_json_not_base64():
    wire = ocp_wire.serialize({"success": True, "shape": _box()})
    assert "\n" not in wire
    # It parses directly as JSON (the old format base64-wrapped the whole thing).
    parsed = json.loads(wire)
    assert parsed["success"] is True
    assert ocp_wire.is_shape_object(parsed["shape"])


def test_deserialize_takes_the_last_nonempty_line():
    wire = ocp_wire.serialize({"success": True, "shape": _box()})
    noisy = "some wrapper progress\n\n" + wire + "\n"
    result = ocp_wire.deserialize(noisy)
    assert result["success"] is True
    _assert_same_solid(result["shape"], _box())


def test_envelope_does_not_execute_payload():
    # There is no code path by which decoding runs arbitrary code; a dict that
    # merely looks structured comes back as plain data.
    payload = {"module": "os", "callable": "system", "args": ["echo hi"]}
    assert ocp_wire.deserialize(ocp_wire.serialize(payload)) == payload
