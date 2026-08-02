# Original code taken from https://gist.github.com/SDI8/3137ee70649e4901913c7c8e6b534ec8

"""
MIT License
Copyright (c) 2022 Simon Dibbern
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# Also influenced by https://github.com/gumyr/build123d/blob/dev/src/build123d/persistence.py

"""
build123d pickle support

name: persistence.py
by:   Jojain & bernhard-42
date: September 8th, 2023

desc:
    This python module enables build123d objects to be pickled.

license:

    Copyright 2023 Jojain & bernhard-42

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

"""

# NOTE: this module used to install 'copyreg' handlers ('register()', with the
# '_reduce_*'/'_inflate_*' pairs) so that OCCT objects could be pickled, because
# the wrapper protocol was a pickle envelope. Pickle has been retired: loading a
# response no longer executes arbitrary code, and no global 'copyreg' state is
# registered any more.
#
# The wrapper protocol and the on-disk shape cache now use the flat, plain-JSON
# format implemented at the bottom of this module:
#
# * A single shape is an object {"name", "label", "brep"} where "brep" is the
#   base64 of the bytes 'BRepTools.Write_s' produces.
# * An assembly is {"name", "label", "assembly": [...]} whose array holds child
#   shape- or sub-assembly-objects; it decodes to a TopoDS_Compound.
# * The request and response envelopes are ordinary JSON objects that carry such
#   a shape object under a key such as "shape" or "wrapped".
#
# Nothing is reconstructed implicitly: decode() only ever turns "brep" back into
# a TopoDS_Shape and "assembly" into a compound.

import base64
import json
import sys
from io import BytesIO
from typing import Any

# Must come before OCP. VTK, which the OCP build we use links against, bundles
# its own older copy of expat under the standard XML_* names, and once that is
# loaded the standard library's pyexpat resolves against it and fails with
# "undefined symbol: XML_SetReparseDeferralEnabled". Importing pyexpat first
# pins it to the right library. Sandbox wrappers reach OCP through this module,
# so this is where the ordering has to be established for them.
import pyexpat  # noqa: F401

# OCP is imported lazily, not at module load: this module is imported by core
# code (via 'import ocp_serialize') that must not pull OCP into the 'import
# partcad' path. 'pyexpat' above stays a module-level import so the expat/VTK
# ordering is still established before OCP is ever loaded, whichever caller
# triggers _ensure_ocp() first.
OCP = None
downcast_LUT = None


def _ensure_ocp():
    """Import OCP and build the downcast table on first use."""
    global OCP, downcast_LUT
    if OCP is not None:
        return

    import OCP as _OCP

    # The submodules have to be imported by name. In OCP 7.9 a bare "import OCP"
    # leaves 'OCP.TopoDS' and friends as unpopulated placeholders, so reaching
    # 'OCP.TopoDS.TopoDS.Vertex_s' through the package alone raises AttributeError.
    # Importing each submodule materializes it; the dotted references below then
    # resolve as they always did.
    import OCP.BRep  # noqa: F401
    import OCP.BRepTools  # noqa: F401
    import OCP.TopAbs  # noqa: F401
    import OCP.TopoDS  # noqa: F401

    OCP = _OCP
    downcast_LUT = {
        _OCP.TopAbs.TopAbs_VERTEX: _OCP.TopoDS.TopoDS.Vertex_s,
        _OCP.TopAbs.TopAbs_EDGE: _OCP.TopoDS.TopoDS.Edge_s,
        _OCP.TopAbs.TopAbs_WIRE: _OCP.TopoDS.TopoDS.Wire_s,
        _OCP.TopAbs.TopAbs_FACE: _OCP.TopoDS.TopoDS.Face_s,
        _OCP.TopAbs.TopAbs_SHELL: _OCP.TopoDS.TopoDS.Shell_s,
        _OCP.TopAbs.TopAbs_SOLID: _OCP.TopoDS.TopoDS.Solid_s,
        _OCP.TopAbs.TopAbs_COMPOUND: _OCP.TopoDS.TopoDS.Compound_s,
        _OCP.TopAbs.TopAbs_COMPSOLID: _OCP.TopoDS.TopoDS.CompSolid_s,
    }


def shapetype(obj):
    """Return TopoDS_Shape's TopAbs_ShapeEnum"""
    if obj.IsNull():
        raise ValueError("Null TopoDS_Shape object")

    return obj.ShapeType()


def downcast(obj):
    """Downcasts a TopoDS object to suitable specialized type

    Args:
      obj: TopoDS_Shape:

    Returns:

    """
    _ensure_ocp()

    f_downcast: Any = downcast_LUT[shapetype(obj)]
    return_value = f_downcast(obj)

    return return_value


#
# Flat BREP wire / cache format
#

# The three object shapes are told apart by which of these keys is present.
KEY_BREP = "brep"
KEY_ASSEMBLY = "assembly"
KEY_BYTES = "__bytes__"
# Optional on a shape/assembly object: the placement, as the packed
# [[tx,ty,tz], [ax,ay,az], angle] form, applied when the object is decoded.
KEY_LOCATION = "location"


def _warn(message: str) -> None:
    """Report a lossy conversion to stderr (the sandboxed wrappers have no logger)."""
    try:
        sys.stderr.write("ocp_serialize: %s\n" % message)
    except Exception:
        pass


def shape_to_brep(shape) -> bytes:
    """Serialize a TopoDS_Shape into the flat BREP byte array."""
    _ensure_ocp()
    with BytesIO() as bio:
        OCP.BRepTools.BRepTools.Write_s(shape, bio)
        return bio.getvalue()


def shape_from_brep(data: bytes):
    """Deserialize a flat BREP byte array into a downcast TopoDS_Shape."""
    _ensure_ocp()
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
    _ensure_ocp()
    result = OCP.TopoDS.TopoDS_Compound()
    builder = OCP.BRep.BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        if shape is not None:
            builder.Add(result, shape)
    return result


def encode_shape(shape, name=None, label=None) -> dict:
    """Represent a single shape as {"name", "label", "brep"}."""
    return {"name": name, "label": label, KEY_BREP: _brep_b64(shape)}


def encode_assembly(children, name=None, label=None) -> dict:
    """Represent an assembly as {"name", "label", "assembly": [...]}.

    'children' is the already-encoded list of shape/assembly objects.
    """
    return {"name": name, "label": label, KEY_ASSEMBLY: list(children)}


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def _toploc_from_packed(packed):
    """Build a TopLoc_Location from the packed [[t], [axis], angle] location form."""
    import math

    from OCP.gp import gp_Trsf, gp_Ax1, gp_Pnt, gp_Dir, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    t, axis, angle = packed
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(axis[0], axis[1], axis[2])), angle * math.pi / 180.0)
    trsf.SetTranslationPart(gp_Vec(t[0], t[1], t[2]))
    return TopLoc_Location(trsf)


def _apply_location(shape, packed):
    """Place 'shape' at the packed location, if one is carried; else return it as is."""
    if packed is None:
        return shape
    return shape.Located(_toploc_from_packed(packed))


def decode_shape(obj):
    """Turn a shape or assembly object back into OCCT geometry.

    A shape object yields its TopoDS_Shape; an assembly object yields a
    TopoDS_Compound of its children (recursively). An optional "location" field
    carried by either kind is applied here - the core builds the assembly tree
    with locations as plain data and never places geometry itself, so this is
    where a child's placement becomes an actual TopLoc. name/label are metadata.
    """
    _ensure_ocp()
    if is_shape_object(obj):
        return _apply_location(_shape_from_b64(obj[KEY_BREP]), obj.get(KEY_LOCATION))
    if is_assembly_object(obj):
        compound = compound_of(decode_shape(child) for child in obj[KEY_ASSEMBLY])
        return _apply_location(compound, obj.get(KEY_LOCATION))
    raise ValueError("Not a shape or assembly object: %r" % (list(obj) if isinstance(obj, dict) else type(obj)))


def encode(obj, name=None, label=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    A TopoDS_Shape becomes a shape object. 'name'/'label', when given, are
    attached to every raw shape encoded - the wrapper protocol uses this to echo
    the name/label the request carried onto the single shape a response returns.
    An already-built shape/assembly object keeps its own name/label. Dicts,
    lists, tuples and sets are walked; exceptions become their message. A
    non-shape OCCT object (a Location/Axis a build123d script showed) drops to
    null - every consumer already discards it - and any other unknown type
    raises, to catch real bugs.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    _ensure_ocp()
    if isinstance(obj, OCP.TopoDS.TopoDS_Shape):
        return encode_shape(obj, name=name, label=label)

    if isinstance(obj, dict):
        # An already-built shape/assembly object keeps its own metadata verbatim.
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
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
        _warn("dropping non-shape OCCT object of type %s" % type(obj))
        return None

    raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))


def decode(obj):
    """Inverse of 'encode()'."""
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            return decode_shape(obj)
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
    """Serialize 'obj' into the single-line form that travels over the pipe.

    Plain JSON, not base64-wrapped JSON: the JSON is already single-line and
    transport-safe (the BREP payload is base64), so an extra base64 layer would
    only cost time and ~1.3x size.
    """
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
