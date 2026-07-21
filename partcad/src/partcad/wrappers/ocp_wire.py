#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Plain-data wire format for the sandboxed wrapper protocol.

The main process and the wrapper scripts running in the sandboxed Python
runtimes exchange requests and responses over stdin/stdout. Historically the
envelope was ``base64(pickle(...))``, which required OCP-aware ``copyreg``
handlers (``ocp_serialize.register()``) to be installed in every process that
touched the protocol, and - much worse - meant that loading a response
executed arbitrary code.

This module replaces that with a plain, non-executable JSON envelope:

* every value that JSON already understands travels as itself;
* OCCT objects are converted into explicit, self-describing marker dicts
  (see ``MARKER_*`` below), the most important of which carries a
  ``TopoDS_Shape`` as base64-encoded BREP bytes;
* nothing is reconstructed implicitly - ``decode()`` only ever instantiates
  the fixed set of OCCT classes listed in ``_DECODERS``.

Both sides of the pipe import this module by bare name off the ``wrappers``
directory, exactly as they used to import ``ocp_serialize``.
"""

import base64
import json
import sys
from io import BytesIO

import OCP.BRep
import OCP.BRepTools
import OCP.gp
import OCP.TopLoc
import OCP.TopoDS

# 'downcast()' and 'shapetype()' remain in 'ocp_serialize' - they are generic
# utilities that have nothing to do with the wire format, and are re-exported
# here only so that this module is self-sufficient for its users.
from ocp_serialize import downcast, shapetype  # noqa: F401


# Marker keys. Each marker dict has exactly one key, which is what makes a
# marker distinguishable from ordinary payload data.
MARKER_TOPODS = "__topods__"
MARKER_TRSF = "__gp_trsf__"
MARKER_GTRSF = "__gp_gtrsf__"
MARKER_MAT = "__gp_mat__"
MARKER_LOCATION = "__toploc__"
MARKER_AX1 = "__gp_ax1__"
MARKER_AX3 = "__gp_ax3__"
MARKER_PLN = "__gp_pln__"
MARKER_PNT = "__gp_pnt__"
MARKER_VEC = "__gp_vec__"
MARKER_DIR = "__gp_dir__"
MARKER_XYZ = "__gp_xyz__"
MARKER_BYTES = "__bytes__"

ALL_MARKERS = frozenset(
    [
        MARKER_TOPODS,
        MARKER_TRSF,
        MARKER_GTRSF,
        MARKER_MAT,
        MARKER_LOCATION,
        MARKER_AX1,
        MARKER_AX3,
        MARKER_PLN,
        MARKER_PNT,
        MARKER_VEC,
        MARKER_DIR,
        MARKER_XYZ,
        MARKER_BYTES,
    ]
)


def _warn(message: str) -> None:
    """Report a lossy conversion.

    This module is imported by the sandboxed wrappers, which have no access to
    the PartCAD logger, so the warning goes to stderr. The main process picks
    up the wrapper's stderr and logs it.
    """
    try:
        sys.stderr.write("ocp_wire: %s\n" % message)
    except Exception:
        pass


#
# gp_* helpers
#


def _trsf_values(trsf) -> list:
    """The 12 significant values of a gp_Trsf, in 'SetValues()' order."""
    return [trsf.Value(i, j) for i in range(1, 4) for j in range(1, 5)]


def _trsf_from_values(values) -> "OCP.gp.gp_Trsf":
    trsf = OCP.gp.gp_Trsf()
    trsf.SetValues(*values)
    return trsf


def _xyz3(obj) -> list:
    return [obj.X(), obj.Y(), obj.Z()]


def _mat_values(mat) -> list:
    """gp_Mat as 9 values, column by column (matching the gp_Mat constructor)."""
    return [_xyz3(mat.Column(1)), _xyz3(mat.Column(2)), _xyz3(mat.Column(3))]


def _mat_from_values(values) -> "OCP.gp.gp_Mat":
    return OCP.gp.gp_Mat(
        OCP.gp.gp_XYZ(*values[0]),
        OCP.gp.gp_XYZ(*values[1]),
        OCP.gp.gp_XYZ(*values[2]),
    )


#
# TopoDS_Shape <-> BREP
#


def shape_to_brep(shape) -> bytes:
    """Serialize a TopoDS_Shape into BREP bytes."""
    with BytesIO() as bio:
        OCP.BRepTools.BRepTools.Write_s(shape, bio)
        return bio.getvalue()


def shape_from_brep(data: bytes):
    """Deserialize BREP bytes into a downcast TopoDS_Shape."""
    with BytesIO(data) as bio:
        shape = OCP.TopoDS.TopoDS_Shape()
        builder = OCP.BRep.BRep_Builder()
        OCP.BRepTools.BRepTools.Read_s(shape, bio, builder)
        return downcast(shape)


def _encode_topods(shape) -> dict:
    location = shape.Location()
    if location.IsIdentity():
        loc_values = None
    else:
        loc_values = _trsf_values(location.Transformation())
    return {
        MARKER_TOPODS: {
            "brep": base64.b64encode(shape_to_brep(shape)).decode("ascii"),
            # The BREP format does carry the top-level location of the shape
            # (verified against OCCT 7.7/7.8 for solids, faces and compounds,
            # with translated, rotated and combined transformations). It is
            # recorded here as well so that 'decode()' can restore it should a
            # future OCCT version, or a shape kind we have not tested, drop it.
            "loc": loc_values,
        }
    }


def _decode_topods(payload):
    if isinstance(payload, str):
        # Tolerate the minimal form: a bare base64 BREP string.
        brep = payload
        loc_values = None
    else:
        brep = payload["brep"]
        loc_values = payload.get("loc")

    shape = shape_from_brep(base64.b64decode(brep))

    if loc_values is not None and shape.Location().IsIdentity():
        # The BREP round-trip dropped the location - put it back. Guarded by
        # 'IsIdentity()' so that a location which did survive is never applied
        # a second time.
        shape.Location(OCP.TopLoc.TopLoc_Location(_trsf_from_values(loc_values)))

    return shape


#
# encode
#

# Ordered: 'TopoDS_Shape' first (it covers every concrete shape class), then
# the gp_* types, which are unrelated to each other.
_ENCODERS = (
    (OCP.TopoDS.TopoDS_Shape, _encode_topods),
    (OCP.TopLoc.TopLoc_Location, lambda o: {MARKER_LOCATION: _trsf_values(o.Transformation())}),
    (OCP.gp.gp_Trsf, lambda o: {MARKER_TRSF: _trsf_values(o)}),
    (
        OCP.gp.gp_GTrsf,
        lambda o: {
            MARKER_GTRSF: {
                "mat": _mat_values(o.VectorialPart()),
                "xyz": _xyz3(o.TranslationPart()),
            }
        },
    ),
    (OCP.gp.gp_Mat, lambda o: {MARKER_MAT: _mat_values(o)}),
    (
        OCP.gp.gp_Ax1,
        lambda o: {MARKER_AX1: {"loc": _xyz3(o.Location()), "dir": _xyz3(o.Direction())}},
    ),
    (
        OCP.gp.gp_Ax3,
        lambda o: {
            MARKER_AX3: {
                "loc": _xyz3(o.Location()),
                "dir": _xyz3(o.Direction()),
                "xdir": _xyz3(o.XDirection()),
                "ydir": _xyz3(o.YDirection()),
            }
        },
    ),
    (
        OCP.gp.gp_Pln,
        lambda o: {
            MARKER_PLN: {
                "loc": _xyz3(o.Position().Location()),
                "dir": _xyz3(o.Position().Direction()),
                "xdir": _xyz3(o.Position().XDirection()),
                "ydir": _xyz3(o.Position().YDirection()),
            }
        },
    ),
    (OCP.gp.gp_Pnt, lambda o: {MARKER_PNT: _xyz3(o)}),
    (OCP.gp.gp_Vec, lambda o: {MARKER_VEC: _xyz3(o)}),
    (OCP.gp.gp_Dir, lambda o: {MARKER_DIR: _xyz3(o)}),
    (OCP.gp.gp_XYZ, lambda o: {MARKER_XYZ: _xyz3(o)}),
)


def encode(obj, strict: bool = True):
    """Convert 'obj' into a structure made only of JSON-native values.

    Dicts, lists, tuples and sets are walked recursively. OCCT objects become
    marker dicts. Exceptions become their string representation, because the
    protocol carries exceptions as messages, not as live objects.

    Anything else raises a 'TypeError' naming the offending type. Pass
    'strict=False' to convert it to 'str(obj)' with a warning instead; that is
    rarely what you want, because silently stringifying a payload turns a
    serialization bug into a confusing failure much deeper in the wrapper.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if isinstance(key, str) and key in ALL_MARKERS:
                raise ValueError("Reserved wire marker used as a dictionary key: %s" % key)
            result[key] = encode(value, strict=strict)
        return result

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item, strict=strict) for item in obj]

    if isinstance(obj, (bytes, bytearray)):
        return {MARKER_BYTES: base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, BaseException):
        # The protocol never carries live exception objects: JSON cannot
        # represent them, and unpickling them used to be a code execution path.
        return str(obj)

    for cls, encoder in _ENCODERS:
        if isinstance(obj, cls):
            return encoder(obj)

    if strict:
        raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))

    _warn("unsupported type %s converted to str()" % type(obj))
    return str(obj)


#
# decode
#

_DECODERS = {
    MARKER_TOPODS: _decode_topods,
    MARKER_LOCATION: lambda v: OCP.TopLoc.TopLoc_Location(_trsf_from_values(v)),
    MARKER_TRSF: _trsf_from_values,
    MARKER_GTRSF: lambda v: OCP.gp.gp_GTrsf(_mat_from_values(v["mat"]), OCP.gp.gp_XYZ(*v["xyz"])),
    MARKER_MAT: _mat_from_values,
    MARKER_AX1: lambda v: OCP.gp.gp_Ax1(OCP.gp.gp_Pnt(*v["loc"]), OCP.gp.gp_Dir(*v["dir"])),
    MARKER_AX3: lambda v: _decode_ax3(v),
    MARKER_PLN: lambda v: OCP.gp.gp_Pln(_decode_ax3(v)),
    MARKER_PNT: lambda v: OCP.gp.gp_Pnt(*v),
    MARKER_VEC: lambda v: OCP.gp.gp_Vec(*v),
    MARKER_DIR: lambda v: OCP.gp.gp_Dir(*v),
    MARKER_XYZ: lambda v: OCP.gp.gp_XYZ(*v),
    MARKER_BYTES: lambda v: base64.b64decode(v),
}


def _decode_ax3(values):
    ax3 = OCP.gp.gp_Ax3(
        OCP.gp.gp_Pnt(*values["loc"]),
        OCP.gp.gp_Dir(*values["dir"]),
        OCP.gp.gp_Dir(*values["xdir"]),
    )
    ax3.SetYDirection(OCP.gp.gp_Dir(*values["ydir"]))
    return ax3


def decode(obj):
    """Inverse of 'encode()'.

    Only the markers listed in '_DECODERS' are ever acted upon, and each one
    only ever constructs a fixed OCCT class. There is no path here by which
    the payload can name a type or a callable of its own choosing.
    """
    if isinstance(obj, dict):
        if len(obj) == 1:
            (key,) = obj.keys()
            decoder = _DECODERS.get(key)
            if decoder is not None:
                return decoder(obj[key])
        return {key: decode(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [decode(item) for item in obj]

    return obj


#
# Envelope
#


def dumps(obj, strict: bool = True) -> str:
    """Serialize 'obj' into the JSON envelope."""
    return json.dumps(encode(obj, strict=strict))


def loads(text) -> object:
    """Deserialize the JSON envelope produced by 'dumps()'."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return decode(json.loads(text))


def serialize(obj, strict: bool = True) -> str:
    """Serialize 'obj' into the base64 form that travels over the pipe."""
    return base64.b64encode(dumps(obj, strict=strict).encode("utf-8")).decode("ascii")


def deserialize(data) -> object:
    """Deserialize the base64 form that travels over the pipe."""
    return loads(base64.b64decode(data))
