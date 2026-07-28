#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pure-Python codec for the shape wire/cache envelope - no OCP, no live shapes.

The core process standardizes on carrying shapes as BREP bytes wrapped in a
small JSON envelope, and never as live OCP objects. This module implements that
envelope without importing OCP, so it is what the core (shape.py, cache_shape.py,
transform.py and the delegating factories) uses to (de)serialize.

The envelope is the same one 'wrappers/ocp_serialize.py' produces and consumes,
so the two are wire-compatible. The difference is deliberate and is the whole
point of the split:

  * The sandbox codec (ocp_serialize) turns a shape object back into a live
    'TopoDS_Shape' on 'decode' - wrappers need the real geometry.
  * This core codec leaves a shape object as its '{"name", "label", "brep"}'
    dict on 'decode' - the core only ever moves the bytes around.

A single shape is '{"name", "label", "brep"}' (base64 BREP); an assembly is
'{"name", "label", "assembly": [...]}'. Requests/responses are ordinary JSON
objects that carry such shape objects under keys like "shape" or "wrapped".
"""

import base64
import json

# The three object shapes are told apart by which of these keys is present.
KEY_BREP = "brep"
KEY_ASSEMBLY = "assembly"
KEY_BYTES = "__bytes__"


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def is_shape_envelope(obj) -> bool:
    """Whether 'obj' is a shape or assembly envelope this codec carries opaquely."""
    return is_shape_object(obj) or is_assembly_object(obj)


def with_metadata(shape: dict, name=None, label=None) -> dict:
    """Return a copy of a shape/assembly envelope with its name/label restamped."""
    out = dict(shape)
    out["name"] = name
    out["label"] = label
    return out


def encode(obj, name=None, label=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    Shape and assembly envelopes are passed through verbatim (their "brep"/
    "assembly" payload and name/label are preserved; any other value is walked).
    Dicts, lists, tuples and sets are walked; bytes become a '__bytes__' object;
    exceptions become their message. A live OCP object is rejected: the core
    must not hand one to this codec - it has nothing to turn it into bytes, and
    encoding geometry is a wrapper's job.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            # An already-built shape/assembly object keeps its metadata verbatim.
            return {
                key: (value if key in (KEY_BREP, KEY_ASSEMBLY, "name", "label") else encode(value, name, label))
                for key, value in obj.items()
            }
        return {key: encode(value, name, label) for key, value in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item, name, label) for item in obj]

    if isinstance(obj, (bytes, bytearray)):
        return {KEY_BYTES: base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, BaseException):
        return str(obj)

    if type(obj).__module__.split(".")[0] == "OCP":
        raise TypeError(
            "shape_envelope cannot encode the live OCP object %s: the core carries BREP "
            "envelopes, so encode it inside a wrapper (ocp_serialize) instead" % type(obj)
        )

    raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))


def decode(obj):
    """Inverse of 'encode()' - but shape/assembly objects stay as dicts.

    Unlike the sandbox codec, this never rebuilds a live 'TopoDS_Shape': a shape
    or assembly object is returned as the dict it already is, so the core keeps
    handling opaque BREP envelopes.
    """
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            return obj
        if KEY_BYTES in obj and len(obj) == 1:
            return base64.b64decode(obj[KEY_BYTES])
        return {key: decode(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [decode(item) for item in obj]

    return obj


def dumps(obj, name=None, label=None) -> str:
    """Serialize 'obj' into a single-line JSON string (used by the cache)."""
    return json.dumps(encode(obj, name=name, label=label))


def loads(text) -> object:
    """Deserialize a JSON string produced by 'dumps()'."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return decode(json.loads(text))


def serialize(obj, name=None, label=None) -> str:
    """Serialize 'obj' into the single-line form that travels over the pipe."""
    return dumps(obj, name=name, label=label)


def deserialize(data) -> object:
    """Deserialize the form produced by 'serialize()'.

    The response is taken as the last non-empty line of 'data', so any leading
    progress a wrapper wrote to stdout is ignored.
    """
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    line = data.strip()
    if "\n" in line:
        for candidate in reversed(line.splitlines()):
            candidate = candidate.strip()
            if candidate:
                line = candidate
                break
    return loads(line)
