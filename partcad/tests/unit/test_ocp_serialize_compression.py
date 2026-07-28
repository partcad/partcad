#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""BREP payloads are zstd-compressed inside the base64 the wire and the cache carry."""

import base64
import json
import os
import sys

import partcad as pc

from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.GProp import GProp_GProps

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _box():
    return BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_zstd_is_available():
    """The fallback to uncompressed payloads must not be what this environment uses.

    '_compress()' degrades quietly so that a foreign environment still works,
    which would also hide the dependency having gone missing from ours.
    """
    assert ocp_serialize._zstd_compress is not None
    assert ocp_serialize._zstd_decompress is not None


def test_brep_payload_is_a_compressed_frame():
    box = _box()
    payload = base64.b64decode(ocp_serialize.encode_shape(box)["brep"])

    assert payload.startswith(ocp_serialize.ZSTD_MAGIC)
    # The whole point: BREP is verbose ASCII, so this is a large margin, not a
    # marginal one.
    assert len(payload) < len(ocp_serialize.shape_to_brep(box))


def test_shape_round_trips_through_the_compression():
    box = _box()
    encoded = ocp_serialize.encode_shape(box, name="box", label="Box")

    # Through the JSON that the pipe and the cache actually carry.
    decoded = ocp_serialize.decode_shape(json.loads(json.dumps(encoded)))

    assert abs(_volume(decoded) - _volume(box)) < 1e-6


def test_assembly_round_trips_through_the_compression():
    box = _box()
    tree = ocp_serialize.encode_assembly(
        [ocp_serialize.encode_shape(box, name="box", label="Box")],
        name="asm",
    )

    decoded = ocp_serialize.decode_shape(json.loads(json.dumps(tree)))

    assert abs(_volume(decoded) - _volume(box)) < 1e-6


def test_uncompressed_payload_is_still_accepted():
    """A payload from a peer without zstd, or from a PartCAD older than it."""
    box = _box()
    legacy = {
        "name": "box",
        "label": "Box",
        "brep": base64.b64encode(ocp_serialize.shape_to_brep(box)).decode("ascii"),
    }

    decoded = ocp_serialize.decode_shape(legacy)

    assert abs(_volume(decoded) - _volume(box)) < 1e-6


def test_serialized_response_round_trips():
    """The envelope a wrapper writes decodes to the shape it was given."""
    box = _box()
    response = ocp_serialize.deserialize(ocp_serialize.serialize({"success": True, "shape": box}))

    assert response["success"] is True
    assert abs(_volume(response["shape"]) - _volume(box)) < 1e-6
