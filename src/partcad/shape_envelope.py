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

A single shape is '{"name", "label", "brep"}'; an assembly is
'{"name", "label", "assembly": [...]}'. Either may also carry an optional
"location" and an optional "properties" (see the keys below).
Requests/responses are ordinary JSON objects that carry such shape objects
under keys like "shape" or "wrapped".

The "brep" payload is zstd-compressed BREP. Which Python type holds it depends
on the layer, and that is the whole reason this module exists:

  * In memory, in the file cache and in every remote cache it is 'bytes' - the
    compressed frame itself. Nothing there needs it to be text, and base64
    would cost a third more space and a copy in each direction.
  * On the wrapper pipe it is a base64 'str', because that hop is JSON and JSON
    has no byte type. 'encode()' puts it into that form and 'decode()' takes it
    straight back out, so the boundary is these two functions and nowhere else.
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
# Optional properties on a shape/assembly object: what the shape reports about
# itself ("material", "color", "physics"), as opposed to the parameters it was
# built from. One key rather than three, so that the envelope's key space stays
# small and everything that identifies an object travels beside its name. Like
# the placement, it is data the core carries opaquely and never interprets.
KEY_PROPERTIES = "properties"


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def is_shape_envelope(obj) -> bool:
    """Whether 'obj' is a shape or assembly envelope this codec carries opaquely."""
    return is_shape_object(obj) or is_assembly_object(obj)


def brep_bytes(value) -> bytes:
    """The zstd-compressed BREP bytes, whether they arrived raw or base64-encoded.

    Bytes are returned as they are rather than copied: this is the hot path for
    every shape that comes out of a cache.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return base64.b64decode(value)


def brep_base64(value) -> str:
    """The same payload as the base64 text that JSON - and only JSON - needs."""
    if isinstance(value, str):
        return value
    return base64.b64encode(value).decode("ascii")


def make_shape(brep, name=None, label=None) -> dict:
    """A shape envelope around a zstd-compressed BREP payload."""
    return {"name": name, "label": label, KEY_BREP: brep_bytes(brep)}


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

    Shape and assembly envelopes keep their metadata; their "brep" payload is
    base64-encoded here, which is the one place the core turns the compressed
    bytes it carries into the text JSON can hold. Dicts, lists, tuples and sets
    are walked; other bytes become a '__bytes__' object; exceptions become their
    message. A live OCP object is rejected: the core must not hand one to this
    codec - it has nothing to turn it into bytes, and encoding geometry is a
    wrapper's job.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            # An already-built shape/assembly object keeps its metadata verbatim.
            encoded = {}
            for key, value in obj.items():
                if key == KEY_BREP:
                    encoded[key] = brep_base64(value)
                elif key == KEY_ASSEMBLY:
                    encoded[key] = [encode(child, name, label) for child in value]
                elif key in (KEY_LOCATION, "name", "label"):
                    encoded[key] = value
                else:
                    encoded[key] = encode(value, name, label)
            return encoded
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
    handling opaque BREP envelopes. The one thing that does change is the "brep"
    payload, which comes off the pipe as base64 text and is handed on as the
    compressed bytes every layer above this one carries.
    """
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            decoded = dict(obj)
            if KEY_BREP in decoded:
                decoded[KEY_BREP] = brep_bytes(decoded[KEY_BREP])
            if KEY_ASSEMBLY in decoded:
                decoded[KEY_ASSEMBLY] = [decode(child) for child in decoded[KEY_ASSEMBLY]]
            return decoded
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
