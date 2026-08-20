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
# Optional placement on a shape/assembly object, carried opaquely by the core
# and turned into a real location by the geometry-side codec (ocp_serialize).
KEY_LOCATION = "location"


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def is_shape_envelope(obj) -> bool:
    """Whether 'obj' is a shape or assembly envelope this codec carries opaquely."""
    return is_shape_object(obj) or is_assembly_object(obj)


def payload_key(obj):
    """The key 'obj' carries its payload under, or None if it is not an envelope."""
    if isinstance(obj, dict):
        if KEY_BREP in obj:
            return KEY_BREP
        if KEY_ASSEMBLY in obj:
            return KEY_ASSEMBLY
    return None


def strip_metadata(obj):
    """Return 'obj' with the outer layer taken off the envelopes it is made of.

    An envelope is a payload ("brep" or "assembly") plus an outer layer that
    says which object this is and where it sits - "name", "label", an optional
    placement, and whatever a later version adds next to them. The payload is
    geometry, which several objects may legitimately share; the outer layer is
    not. Splitting them is what lets the shape cache key an entry on the
    geometry alone (see cache_shape.py).

    Only the envelope 'obj' itself is - or the ones a list of them holds - are
    stripped. The children nested inside an assembly keep their own outer
    layers: those describe the assembly's structure, not the assembly.
    """
    if isinstance(obj, list):
        return [strip_metadata(item) for item in obj]
    key = payload_key(obj)
    if key is None:
        return obj
    return {key: obj[key]}


def apply_metadata(obj, metadata):
    """Inverse of 'strip_metadata()': wrap 'metadata' around the payloads in 'obj'."""
    if isinstance(obj, list):
        return [apply_metadata(item, metadata) for item in obj]
    key = payload_key(obj)
    if key is None:
        return obj
    wrapped = dict(metadata or {})
    wrapped[key] = obj[key]
    return wrapped


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
                key: (
                    value
                    if key in (KEY_BREP, KEY_ASSEMBLY, KEY_LOCATION, "name", "label")
                    else encode(value, name, label)
                )
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
    if not line:
        # A wrapper can exit 0 having written nothing (no result and no stderr),
        # which slips past the exit-code and stderr checks in the callers. Say so
        # here rather than letting loads() raise a bare, contextless JSONDecodeError.
        raise ValueError("the wrapper produced no output to deserialize (empty response)")
    return loads(line)
