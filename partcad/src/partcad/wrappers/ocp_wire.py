#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Flat BREP wire format for the sandboxed wrapper protocol and the shape cache.

The main process and the wrapper scripts running in the sandboxed Python
runtimes exchange requests and responses over stdin/stdout, and the same
serialization backs the on-disk shape cache. Historically the envelope was
``base64(pickle(...))``, which required OCP-aware ``copyreg`` handlers and, far
worse, executed arbitrary code on load.

This module is a plain, non-executable JSON format built around raw BREP bytes:

* A single shape is an object ``{"name", "label", "brep"}`` where ``brep`` is
  the base64 of the bytes ``BRepTools.Write_s`` produces - the same flat byte
  array ``wrapper_render_brep``/``wrapper_brep`` write and read.
* An assembly is an object ``{"name", "label", "assembly": [...]}`` whose
  ``assembly`` array holds child objects, each of which is itself a shape (with
  ``"brep"``) or a nested sub-assembly (with ``"assembly"``).
* Everything else JSON already understands travels as itself; the request and
  response envelopes are ordinary JSON objects that carry such a shape object
  under a key such as ``"shape"`` or ``"wrapped"``.

Nothing is reconstructed implicitly: ``decode()`` only ever turns ``"brep"`` back
into a ``TopoDS_Shape`` and ``"assembly"`` into a ``TopoDS_Compound``. There is
no marker naming a type or a callable of the payload's choosing.

Both sides of the pipe import this module by bare name off the ``wrappers``
directory.
"""

import base64
import json
import sys
from io import BytesIO

import OCP.BRep
import OCP.BRepTools
import OCP.TopoDS

# 'downcast()' and 'shapetype()' remain in 'ocp_serialize' - they are generic
# utilities unrelated to the wire format, re-exported here so this module is
# self-sufficient for its users.
from ocp_serialize import downcast, shapetype  # noqa: F401


# The three object shapes are told apart by which of these keys is present.
KEY_BREP = "brep"
KEY_ASSEMBLY = "assembly"
KEY_BYTES = "__bytes__"


def _warn(message: str) -> None:
    """Report a lossy conversion to stderr.

    The sandboxed wrappers have no access to the PartCAD logger; the main
    process picks up their stderr and logs it.
    """
    try:
        sys.stderr.write("ocp_wire: %s\n" % message)
    except Exception:
        pass


#
# TopoDS_Shape <-> flat BREP bytes
#


def shape_to_brep(shape) -> bytes:
    """Serialize a TopoDS_Shape into the flat BREP byte array."""
    with BytesIO() as bio:
        OCP.BRepTools.BRepTools.Write_s(shape, bio)
        return bio.getvalue()


def shape_from_brep(data: bytes):
    """Deserialize a flat BREP byte array into a downcast TopoDS_Shape."""
    with BytesIO(data) as bio:
        shape = OCP.TopoDS.TopoDS_Shape()
        builder = OCP.BRep.BRep_Builder()
        OCP.BRepTools.BRepTools.Read_s(shape, bio, builder)
        return downcast(shape)


def _brep_b64(shape) -> str:
    return base64.b64encode(shape_to_brep(shape)).decode("ascii")


def _shape_from_b64(brep_b64: str):
    return shape_from_brep(base64.b64decode(brep_b64))


def compound_of(shapes):
    """Combine OCCT shapes into a single TopoDS_Compound."""
    result = OCP.TopoDS.TopoDS_Compound()
    builder = OCP.BRep.BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        if shape is not None:
            builder.Add(result, shape)
    return result


#
# Shape / assembly objects
#


def encode_shape(shape, name=None, label=None) -> dict:
    """Represent a single shape as ``{"name", "label", "brep"}``."""
    return {"name": name, "label": label, KEY_BREP: _brep_b64(shape)}


def encode_assembly(children, name=None, label=None) -> dict:
    """Represent an assembly as ``{"name", "label", "assembly": [...]}``.

    ``children`` is the already-encoded list of shape/assembly objects.
    """
    return {"name": name, "label": label, KEY_ASSEMBLY: list(children)}


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def decode_shape(obj):
    """Turn a shape or assembly object back into OCCT geometry.

    A shape object yields its ``TopoDS_Shape``; an assembly object yields a
    ``TopoDS_Compound`` of its children (recursively). ``name``/``label`` are
    metadata and do not affect the geometry.
    """
    if is_shape_object(obj):
        return _shape_from_b64(obj[KEY_BREP])
    if is_assembly_object(obj):
        return compound_of(decode_shape(child) for child in obj[KEY_ASSEMBLY])
    raise ValueError("Not a shape or assembly object: %r" % (list(obj) if isinstance(obj, dict) else type(obj)))


#
# Envelope encode / decode
#


def encode(obj, name=None, label=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    A TopoDS_Shape becomes a shape object (carrying 'name'/'label' when given).
    Dicts, lists, tuples and sets are walked; exceptions become their message.
    'name'/'label' apply only to a shape passed directly as 'obj'; a shape found
    nested inside a container carries no name/label unless it was built
    explicitly with encode_shape()/encode_assembly() by the caller.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, OCP.TopoDS.TopoDS_Shape):
        return encode_shape(obj, name=name, label=label)

    if isinstance(obj, dict):
        # An already-built shape/assembly object passes through unchanged.
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            return {
                key: (value if key in (KEY_BREP, KEY_ASSEMBLY, "name", "label") else encode(value))
                for key, value in obj.items()
            }
        return {key: encode(value) for key, value in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item) for item in obj]

    if isinstance(obj, (bytes, bytearray)):
        return {KEY_BYTES: base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, BaseException):
        # Exceptions travel as their message; JSON cannot carry a live object,
        # and reconstructing one used to be a code-execution path.
        return str(obj)

    if type(obj).__module__.split(".")[0] == "OCP":
        # A non-shape OCCT object (e.g. a TopLoc_Location or gp_Ax1 a build123d
        # script handed to show_object). These carry no geometry and every
        # consumer already discards them, so drop them to null rather than fail
        # or reintroduce a per-type marker for something nobody reads.
        _warn("dropping non-shape OCCT object of type %s" % type(obj))
        return None

    raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))


def decode(obj):
    """Inverse of 'encode()'.

    A shape object becomes a TopoDS_Shape, an assembly object a TopoDS_Compound,
    the bytes object raw bytes; every other dict/list is walked.
    """
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            return decode_shape(obj)
        if KEY_BYTES in obj and len(obj) == 1:
            return base64.b64decode(obj[KEY_BYTES])
        return {key: decode(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [decode(item) for item in obj]

    return obj


#
# Envelope <-> text / wire
#


def dumps(obj, name=None, label=None) -> str:
    """Serialize 'obj' into a single-line JSON string (used by the cache)."""
    return json.dumps(encode(obj, name=name, label=label))


def loads(text) -> object:
    """Deserialize a JSON string produced by 'dumps()'."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return decode(json.loads(text))


def serialize(obj, name=None, label=None) -> str:
    """Serialize 'obj' into the single-line form that travels over the pipe.

    Unlike the old format this is plain JSON, not base64-wrapped JSON: the JSON
    is already single-line and transport-safe (the BREP payload is base64), so
    the extra base64 layer only cost time and ~1.3x size.
    """
    return dumps(obj, name=name, label=label)


def deserialize(data) -> object:
    """Deserialize the form produced by 'serialize()'.

    The response is taken as the last non-empty line of 'data', so any leading
    progress a wrapper wrote to stdout is ignored and callers need not split the
    output themselves.
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
