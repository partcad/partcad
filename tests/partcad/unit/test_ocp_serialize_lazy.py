#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""An answer with no geometry in it must not load the CAD kernel to say so.

Every wrapper call is a process of its own, and importing OCP is the better part
of a second in it. A repository plugin's answer is a dict of strings, and PartCAD
asks a plugin one key at a time - hundreds of times over to list a large package
tree - so a kernel loaded to decide that a dict is not a shape was most of what
each of those calls cost.

The "did it load" half is checked in a subprocess, because within one test
session something else has already imported OCP.
"""

import base64
import json
import os
import subprocess
import sys

import pytest

import partcad as pc

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")
sys.path.append(WRAPPERS)
import ocp_serialize  # noqa: E402


def _serialized_without_ocp(expression):
    """Serialize 'expression' in a fresh interpreter, both ways; (JSON, frame, whether OCP loaded).

    Both forms an answer takes - JSON for a request that came as JSON, a frame
    for one that came as a frame - and the kernel loaded by neither.
    """
    script = "\n".join(
        [
            "import base64, json, sys",
            "sys.path.insert(0, %r)" % WRAPPERS,
            "import ocp_serialize",
            "out = ocp_serialize.dumps(%s)" % expression,
            "framed = base64.b64encode(ocp_serialize.serialize(%s)).decode()" % expression,
            'print(json.dumps({"ocp": "OCP" in sys.modules, "out": out, "framed": framed}))',
        ]
    )
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    answer = json.loads(completed.stdout.strip().splitlines()[-1])
    framed = ocp_serialize.deserialize_raw(base64.b64decode(answer["framed"]))
    return json.loads(answer["out"]), framed, answer["ocp"]


def test_a_geometry_free_answer_does_not_import_the_kernel():
    """What a repository plugin returns: nested dicts, lists and scalars."""
    payload = {"result": {"3001": {"type": ":ldraw", "implements": {"stud": [1, 2.5, None, True]}}}}
    out, framed, ocp = _serialized_without_ocp(repr(payload))
    assert ocp is False
    assert out == payload
    assert framed == payload


def test_an_exception_answer_does_not_import_the_kernel_either():
    out, framed, ocp = _serialized_without_ocp('{"exception": ValueError("no such part")}')
    assert ocp is False
    assert out == {"exception": "no such part"}
    assert framed == {"exception": "no such part"}


def test_bytes_still_travel_without_the_kernel():
    out, framed, ocp = _serialized_without_ocp('{"blob": b"abc"}')
    assert ocp is False
    assert base64.b64decode(out["blob"][ocp_serialize.KEY_BYTES]) == b"abc"
    # Raw in a frame: an attachment, not base64.
    assert framed == {"blob": b"abc"}


def _volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_a_shape_is_still_encoded_as_a_shape():
    """The lazy import changes when the kernel is loaded, not what is produced."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    framed = ocp_serialize.serialize({"shape": box}, name="n", label="l")
    encoded = ocp_serialize.deserialize_raw(framed)
    assert isinstance(encoded["shape"][ocp_serialize.KEY_BREP], bytes)
    assert encoded["shape"]["name"] == "n" and encoded["shape"]["label"] == "l"

    for form in (framed, ocp_serialize.dumps({"shape": box})):
        restored = ocp_serialize.deserialize(form)["shape"]
        assert _volume(restored) == pytest.approx(_volume(box))


def test_a_shape_nested_in_a_container_is_still_found():
    """Containers are walked before the kernel is reached for, not instead of."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    box = BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape()
    encoded = ocp_serialize.deserialize_raw(ocp_serialize.serialize({"parts": [{"a": box}]}))
    assert ocp_serialize.KEY_BREP in encoded["parts"][0]["a"]


def test_a_non_shape_occt_object_is_still_dropped():
    """It used to be found by the isinstance() that ran first; now by the last check."""
    from OCP.gp import gp_Pnt

    assert ocp_serialize.deserialize_raw(ocp_serialize.serialize({"where": gp_Pnt(1, 2, 3)})) == {"where": None}


def test_an_unencodable_type_still_raises():
    with pytest.raises(TypeError):
        ocp_serialize.serialize({"bad": object()})
