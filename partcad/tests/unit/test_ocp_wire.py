#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Round-trip tests for the wrapper protocol wire format.

The wrapper protocol carries OCCT shapes as base64-encoded BREP bytes inside a
plain JSON envelope. These tests pin down that a shape survives the round trip
numerically - volume, centre of mass, bounding box - and, most importantly,
that its 'TopLoc_Location' is not lost, which is the failure mode a BREP round
trip is most likely to introduce silently.
"""

import base64
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
from OCP.gp import gp_Ax1, gp_Ax3, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound, TopoDS_Iterator

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


def _trsf_values(trsf):
    return [trsf.Value(i, j) for i in range(1, 4) for j in range(1, 5)]


def _assert_close(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert math.isclose(a, e, rel_tol=1e-9, abs_tol=1e-9), f"{actual} != {expected}"


def _round_trip(obj):
    """Send 'obj' through the full wire form and back."""
    return ocp_wire.deserialize(ocp_wire.serialize({"payload": obj}))["payload"]


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


@pytest.mark.parametrize(
    "make_shape",
    [_box, BRepPrimAPI_MakeSphere(7.5).Shape, _compound],
    ids=["solid_box", "solid_sphere", "compound"],
)
def test_ocp_wire_solid_round_trip(make_shape):
    """A 3D shape keeps its volume, centre of mass and bounding box."""
    shape = make_shape()
    result = _round_trip(shape)

    assert result.ShapeType() == shape.ShapeType()
    assert type(result) is type(ocp_wire.downcast(shape))

    mass, com = _volume(shape)
    result_mass, result_com = _volume(result)
    _assert_close([result_mass], [mass])
    _assert_close(result_com, com)
    _assert_close(_bbox(result), _bbox(shape))
    assert result.Orientation() == shape.Orientation()


def test_ocp_wire_face_round_trip():
    """A 2D shape keeps its area, centroid and bounding box."""
    face = _face()
    result = _round_trip(face)

    assert result.ShapeType() == face.ShapeType()
    area, com = _surface(face)
    result_area, result_com = _surface(result)
    _assert_close([result_area], [area])
    _assert_close(result_com, com)
    _assert_close(_bbox(result), _bbox(face))


@pytest.mark.parametrize(
    "make_shape",
    [_box, _face, _compound],
    ids=["solid", "face", "compound"],
)
@pytest.mark.parametrize(
    "make_trsf",
    [
        lambda: _translation(100.0, 200.0, 300.0),
        _rotation,
        lambda: _translation(100.0, 200.0, 300.0).Multiplied(_rotation()),
    ],
    ids=["translation", "rotation", "combined"],
)
def test_ocp_wire_location_survives(make_shape, make_trsf):
    """The top-level TopLoc_Location must not be lost by the BREP round trip.

    'BRepTools.Write_s()' does record the top-level location, but the envelope
    also carries it explicitly so that it can be restored if it ever is not.
    """
    trsf = make_trsf()
    shape = make_shape().Moved(TopLoc_Location(trsf))
    assert not shape.Location().IsIdentity()

    result = _round_trip(shape)

    assert not result.Location().IsIdentity(), "the location was lost"
    _assert_close(_trsf_values(result.Location().Transformation()), _trsf_values(trsf))
    _assert_close(_bbox(result), _bbox(shape))


def test_ocp_wire_nested_location_survives():
    """A location on a child of a compound survives too."""
    builder = TopoDS_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, _box().Moved(TopLoc_Location(_translation(100.0, 200.0, 300.0))))
    builder.Add(compound, BRepPrimAPI_MakeSphere(7.5).Shape())

    result = _round_trip(compound)

    identities = []
    iterator = TopoDS_Iterator(result)
    while iterator.More():
        identities.append(iterator.Value().Location().IsIdentity())
        iterator.Next()
    assert identities == [False, True]
    _assert_close(_bbox(result), _bbox(compound))


def test_ocp_wire_location_is_restored_when_brep_drops_it():
    """The explicit location in the marker is a working fallback.

    Simulated by handing 'decode()' a marker whose BREP payload has no
    location but whose 'loc' field does.
    """
    trsf = _translation(100.0, 200.0, 300.0)
    marker = ocp_wire.encode(_box())
    assert marker[ocp_wire.MARKER_TOPODS]["loc"] is None
    marker[ocp_wire.MARKER_TOPODS]["loc"] = _trsf_values(trsf)

    result = ocp_wire.decode(marker)

    assert not result.Location().IsIdentity()
    _assert_close(_trsf_values(result.Location().Transformation()), _trsf_values(trsf))
    _assert_close(_bbox(result), _bbox(_box().Moved(TopLoc_Location(trsf))))


def test_ocp_wire_location_is_not_applied_twice():
    """A location that did survive the BREP round trip is left alone."""
    trsf = _translation(100.0, 200.0, 300.0)
    shape = _box().Moved(TopLoc_Location(trsf))
    _assert_close(_bbox(ocp_wire.decode(ocp_wire.encode(shape))), _bbox(shape))


def test_ocp_wire_gp_types_round_trip():
    """Every OCCT type that can cross the wrapper boundary survives."""
    trsf = _translation(100.0, 200.0, 300.0).Multiplied(_rotation())

    result = _round_trip(trsf)
    assert isinstance(result, gp_Trsf)
    _assert_close(_trsf_values(result), _trsf_values(trsf))

    location = TopLoc_Location(trsf)
    result = _round_trip(location)
    assert isinstance(result, TopLoc_Location)
    _assert_close(_trsf_values(result.Transformation()), _trsf_values(location.Transformation()))

    ax1 = gp_Ax1(gp_Pnt(1.0, 2.0, 3.0), gp_Dir(0.0, 1.0, 0.0))
    result = _round_trip(ax1)
    assert isinstance(result, gp_Ax1)
    _assert_close(
        [result.Location().X(), result.Location().Y(), result.Location().Z()],
        [1.0, 2.0, 3.0],
    )
    _assert_close(
        [result.Direction().X(), result.Direction().Y(), result.Direction().Z()],
        [0.0, 1.0, 0.0],
    )

    ax3 = gp_Ax3(gp_Pnt(1.0, 2.0, 3.0), gp_Dir(0.0, 0.0, 1.0), gp_Dir(1.0, 0.0, 0.0))
    result = _round_trip(ax3)
    assert isinstance(result, gp_Ax3)
    _assert_close(
        [result.XDirection().X(), result.XDirection().Y(), result.XDirection().Z()],
        [1.0, 0.0, 0.0],
    )

    point = _round_trip(gp_Pnt(1.5, -2.5, 3.5))
    assert isinstance(point, gp_Pnt)
    _assert_close([point.X(), point.Y(), point.Z()], [1.5, -2.5, 3.5])


def test_ocp_wire_envelope_carries_plain_data_unchanged():
    request = {
        "tolerance": 0.1,
        "ascii": False,
        "viewport_origin": [100, -100, 100],
        "build_parameters": {"a": 1, "b": "two", "c": None},
        "patch": {"\\Z": "\nshow(x)\n"},
    }
    assert ocp_wire.deserialize(ocp_wire.serialize(request)) == request


def test_ocp_wire_envelope_carries_nested_shape_lists():
    """The build123d and cadquery wrappers return nested lists of shapes."""
    box = _box()
    response = {
        "success": True,
        "exception": None,
        "shapes": [box, "a string", [_face(), [BRepPrimAPI_MakeSphere(4.0).Shape()]], None],
    }
    result = ocp_wire.deserialize(ocp_wire.serialize(response))

    assert result["success"] is True
    assert result["exception"] is None
    assert result["shapes"][1] == "a string"
    assert result["shapes"][3] is None
    _assert_close([_volume(result["shapes"][0])[0]], [_volume(box)[0]])
    _assert_close(_bbox(result["shapes"][2][0]), _bbox(_face()))


def test_ocp_wire_exceptions_become_strings():
    """Exceptions travel as messages: JSON cannot carry a live exception."""
    result = ocp_wire.deserialize(ocp_wire.serialize({"exception": ValueError("boom")}))
    assert result["exception"] == "boom"

    # 'None' must stay 'None' - consumers distinguish it from an empty message.
    result = ocp_wire.deserialize(ocp_wire.serialize({"exception": None}))
    assert result["exception"] is None


def test_ocp_wire_envelope_does_not_execute_payload():
    """Unlike pickle, the envelope cannot name a type or a callable."""
    payload = '{"a": {"__reduce__": ["os.system", ["echo pwned"]]}}'
    assert ocp_wire.loads(payload) == {"a": {"__reduce__": ["os.system", ["echo pwned"]]}}


def test_ocp_wire_rejects_reserved_marker_keys():
    """Payload data may not shadow a marker, which would corrupt decoding."""
    with pytest.raises(ValueError):
        ocp_wire.dumps({ocp_wire.MARKER_TOPODS: "not a shape"})


def test_ocp_wire_marker_carries_plain_brep_bytes():
    """The marker payload is the very same BREP stream OCCT writes itself."""
    box = _box()

    stream = BytesIO()
    BRepTools.Write_s(box, stream)
    assert ocp_wire.shape_to_brep(box) == stream.getvalue()

    shape = ocp_wire.shape_from_brep(stream.getvalue())
    _assert_close([_volume(shape)[0]], [_volume(box)[0]])

    marker = ocp_wire.encode(box)
    assert set(marker) == {ocp_wire.MARKER_TOPODS}
    assert base64.b64decode(marker[ocp_wire.MARKER_TOPODS]["brep"]) == stream.getvalue()
