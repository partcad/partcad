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
#   base64 of the zstd-compressed bytes 'BinTools.Write_s' produces - OCCT's
#   binary BREP, see 'shape_to_brep()'. The ASCII BREP 'BRepTools.Write_s'
#   produces is still read wherever a payload is: see 'shape_from_brep()'.
# * An assembly is {"name", "label", "assembly": [...]} whose array holds child
#   shape- or sub-assembly-objects; it decodes to a TopoDS_Compound.
# * The request and response envelopes are ordinary JSON objects that carry such
#   a shape object under a key such as "shape" or "wrapped".
#
# Nothing is reconstructed implicitly: decode() only ever turns "brep" back into
# a TopoDS_Shape and "assembly" into a compound.

import base64
import hashlib
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
# The 'BinTools_FormatVersion' payloads are written in, or None where this OCP
# has no binary writer to ask for one (see 'shape_to_brep()'). Set with OCP.
_binary_version = None

try:
    # Python 3.14 and newer carry zstd in the standard library. One statement,
    # so that the branch not taken on this interpreter is a single line.
    from compression.zstd import compress as _zstd_compress, decompress as _zstd_decompress
except ImportError:
    try:
        # Below 3.14, the very same module, backported. PartCAD depends on it
        # and installs it into every sandbox (see sandbox_versions.ZSTD), so
        # both ends of the pipe produce and read the same frames.
        from backports.zstd import compress as _zstd_compress, decompress as _zstd_decompress
    except ImportError:  # pragma: no cover - no zstd at all, see _compress()
        _zstd_compress = None
        _zstd_decompress = None


def _ensure_ocp():
    """Import OCP and build the downcast table on first use."""
    global OCP, downcast_LUT, _binary_version
    if OCP is not None:
        return

    import OCP as _OCP

    # The submodules have to be imported by name. In OCP 7.9 a bare "import OCP"
    # leaves 'OCP.TopoDS' and friends as unpopulated placeholders, so reaching
    # 'OCP.TopoDS.TopoDS.Vertex_s' through the package alone raises AttributeError.
    # Importing each submodule materializes it; the dotted references below then
    # resolve as they always did.
    import OCP.BinTools  # noqa: F401
    import OCP.BRep  # noqa: F401
    import OCP.BRepTools  # noqa: F401
    import OCP.TopAbs  # noqa: F401
    import OCP.TopExp  # noqa: F401
    import OCP.TopoDS  # noqa: F401

    # Named, never 'BinTools_FormatVersion_CURRENT': see BINARY_FORMAT_VERSION.
    # Absent from an OCCT older than 7.6, which has no versioned binary writer;
    # such a peer writes ASCII, which every reader here still reads.
    versions = getattr(_OCP.BinTools, "BinTools_FormatVersion", None)
    _binary_version = getattr(versions, "BinTools_FormatVersion_VERSION_%d" % BINARY_FORMAT_VERSION, None)

    # Build the table into a local first, then publish 'downcast_LUT' before
    # 'OCP'. The guard above returns as soon as 'OCP is not None', so a second
    # thread that sees OCP published must also see a fully-built table - otherwise
    # its downcast() would find downcast_LUT still None and raise. (PartCAD runs
    # CPU-heavy work in a thread pool, so concurrent first use is reachable.)
    lut = {
        _OCP.TopAbs.TopAbs_VERTEX: _OCP.TopoDS.TopoDS.Vertex_s,
        _OCP.TopAbs.TopAbs_EDGE: _OCP.TopoDS.TopoDS.Edge_s,
        _OCP.TopAbs.TopAbs_WIRE: _OCP.TopoDS.TopoDS.Wire_s,
        _OCP.TopAbs.TopAbs_FACE: _OCP.TopoDS.TopoDS.Face_s,
        _OCP.TopAbs.TopAbs_SHELL: _OCP.TopoDS.TopoDS.Shell_s,
        _OCP.TopAbs.TopAbs_SOLID: _OCP.TopoDS.TopoDS.Solid_s,
        _OCP.TopAbs.TopAbs_COMPOUND: _OCP.TopoDS.TopoDS.Compound_s,
        _OCP.TopAbs.TopAbs_COMPSOLID: _OCP.TopoDS.TopoDS.CompSolid_s,
    }
    downcast_LUT = lut
    OCP = _OCP


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
# The other form a node's geometry can take: binary glTF, as the bytes
# 'encode_gltf()' leaves it, written by 'wrapper_gltf.py'. The core's copy of this key, and the reason
# there are two forms at all, is 'partcad.shape_envelope'.
KEY_GLTF = "gltf"
# On the root of a converted tree: every distinct piece of tessellated geometry in
# it, keyed by 'payload_digest()' of the exact geometry it came from, with whatever
# had geometry naming its entry through KEY_GLTF_REF. One entry however many nodes
# are made of it. The core's copy of both, and what the sharing buys, is
# 'partcad.shape_envelope'.
KEY_GEOMETRY = "geometry"
KEY_GLTF_REF = "gltfRef"
KEY_BYTES = "__bytes__"
# On the top level of a serialized document: every BREP payload it carries, once
# each, keyed by 'payload_digest'; and on a node, which entry is its geometry, in
# place of KEY_BREP. The same two keys as 'shape_envelope.KEY_BREPS' and
# 'KEY_BREP_REF', and the same rule: they exist only in the serialized form.
# 'loads()' and 'deserialize_raw()' put every payload back on the nodes naming
# it - the one string object for all of them - before anything here or in an
# implementation sees the tree, so a reader of a tree never meets either key.
KEY_BREPS = "__breps__"
KEY_BREP_REF = "brepRef"
# The cost of naming a payload rather than carrying it, as
# 'shape_envelope._REFERENCE_COST' has it.
_REFERENCE_COST = 64 + 16
# Optional on a shape/assembly object: the placement, as the packed
# [[tx,ty,tz], [ax,ay,az], angle] form, applied when the object is decoded.
KEY_LOCATION = "location"
# On a shape object of a tree 'decode_tree()' hands back, and never on one that
# travels: the shape's own geometry, decoded, in its own frame - KEY_LOCATION
# beside it still says where it sits in its parent. Put there beside KEY_BREP
# rather than in place of it, so what reads a node as an envelope (decoding it
# again, or keying a mesh by its payload) reads it as it always did.
KEY_SHAPE = "shape"
# Optional on a shape object: which child of the shape its "brep" payload holds
# this node is - an index into that shape's children, in the order
# 'TopoDS_Iterator' visits them - when the node is a piece of a shape rather than
# a shape of its own. That is what a script's components are: the solids, faces
# and wires of the compound it returned, which used to be written, measured,
# sent and cached a second time beside it. Now a component carries the
# compound's own payload - the same string, which the payload table writes
# once - and says which child of it it is ('encode_combined()'). The core's twin
# of this constant is in 'shape_envelope.py'.
#
# 'decode_shape()', 'decode_tree()' and 'decode()' honour it, so a reader that
# decodes a node through them gets the child and nothing else. A reader that
# opens a payload itself ('shape_from_payload()', or keying a mesh by
# 'payload_digest()') would have to honour it too; the two that do are handed
# trees, whose nodes never carry it.
KEY_CHILD = "child"
# Optional on a shape object: everything learnt about this shape by whatever
# produced it, at the moment it was produced. The one channel for such
# knowledge; the core's twin of this constant, and of the three section names
# below, is in 'shape_envelope.py', which documents what each section holds.
#
# 'measurements' is filled in by 'encode_shape()' below rather than by any
# individual wrapper: encoding is the one thing every wrapper that returns a
# shape does, and it is the last moment the live OCCT object exists. The other
# two are filled in by the wrapper that read the source file, which is the only
# process that ever has it open.
KEY_METADATA = "metadata"
METADATA_MEASUREMENTS = "measurements"
METADATA_ANNOTATIONS = "annotations"
METADATA_SECTIONS = "sections"
# What a part's request asks the wrapper building it to do to it on its way
# out, and the section of that wrapper's answer that says how far it got.
# Written by 'wrapper_common.finished()'; the core's twins, and what each one
# holds, are 'shape_envelope.KEY_FINISH' and 'METADATA_FINISHED'.
KEY_FINISH = "finish"
METADATA_FINISHED = "finished"
FINISHED_VALIDATED = "validated"
FINISHED_DECLINED = "declined"

# A payload is OCCT's *binary* BREP ('BinTools'), not the ASCII one
# ('BRepTools') it used to be. Every shape that crosses the wrapper pipe or lands
# in the shape cache is written and read once at least, and on the parts under
# examples/ (STEP parts, an SDF one) writing and compressing a binary payload is
# four to eight times faster than an ASCII one, reading it one and a half to
# five times faster, and it is 40-55% smaller before zstd and 5-28% smaller
# after it. It is also exact: ASCII prints a double to fifteen significant
# digits, so every hop through it moved a vertex - by up to 5e-11 on a large
# part - and a part that went through three wrappers had been rounded three
# times.
#
# The version is named rather than left at 'BinTools_FormatVersion_CURRENT',
# because the writer and the reader are not always the same OCCT: a payload
# the core encodes in process, with whatever OCP its user installed, is read in
# a sandbox, and one written in a plugin's container is read in PartCAD's own.
# A writer that moved to a newer CURRENT would write what an older reader
# refuses. 4 is what OCCT 7.6 and later write by default and read, which is
# every OCP PartCAD provisions (sandbox_versions.OCP and CADQUERY_OCP, both
# 7.9.3), and it is the first version that keeps the normals of a face that is
# nothing but triangles - an imported glTF's - which the ASCII payloads kept
# too.
BINARY_FORMAT_VERSION = 4

# What a binary payload starts with: 'BinTools' writes a newline and then
# "Open CASCADE Topology V4, (c) Open Cascade". The ASCII one starts with
# "CASCADE Topology" after its newline, or with "DBRep_DrawableShape" when it
# was saved from Draw - which is why this is matched at the start, past the
# whitespace, and never as a substring: the ASCII marker is inside this one.
BINARY_MAGIC = b"Open CASCADE Topology"
# How much of a payload the sniff looks at.
_SNIFF_WINDOW = 64

# The header of the section of a binary payload that holds triangulations, and
# its count. A payload written without triangles holds only those of faces that
# have no surface, so a count other than 0 is how 'shape_to_brep()' learns that
# a shape is a mesh without walking its faces.
_TRIANGULATIONS = b"Triangulations "

# The payload, zstd-compressed, is by far the largest thing that either travels
# the wrapper pipe or lands in the shape cache. Compressing it before the base64
# (which inflates whatever it is given by another third) is what keeps both
# affordable.
#
# Level 3 is zstd's own default: on this data the levels above it cost several
# times the CPU for a few percent of size, and the payload is on its way to a
# subprocess or a disk either way.
ZSTD_LEVEL = 3

# The zstd frame header, used to tell a compressed payload from a plain one.
# Sniffing it rather than declaring the encoding in the JSON keeps the format
# unchanged, and it cannot collide with a raw payload: BREP, binary or ASCII,
# always begins with its own text header (see BINARY_MAGIC).
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# Whether the "no zstd here" warning has already been issued. It applies to
# every payload, and the interesting case is a wrapper writing it once per
# process rather than once per shape.
_zstd_warned = False


def _warn(message: str) -> None:
    """Report a lossy conversion to stderr (the sandboxed wrappers have no logger)."""
    try:
        sys.stderr.write("ocp_serialize: %s\n" % message)
    except Exception:
        pass


def _compress(data: bytes) -> bytes:
    """Compress BREP bytes, or pass them through where zstd is unavailable.

    Every environment PartCAD provisions has zstd, so the fallback is for an
    environment somebody else assembled. Uncompressed output stays readable
    everywhere, because '_decompress()' recognizes both forms.
    """
    if _zstd_compress is None:
        global _zstd_warned
        if not _zstd_warned:
            _zstd_warned = True
            _warn("zstd is not available, leaving BREP payloads uncompressed")
        return data

    return _zstd_compress(data, ZSTD_LEVEL)


def _decompress(data: bytes) -> bytes:
    """Inverse of '_compress()', also accepting a payload that was never compressed."""
    if not data.startswith(ZSTD_MAGIC):
        # Written either by a peer without zstd or by a PartCAD older than the
        # compression - the shape cache is versioned (see cache_hash.VERSION)
        # and no longer serves those entries, but the pipe can still carry one.
        return data

    if _zstd_decompress is None:
        raise RuntimeError(
            "Received a zstd-compressed BREP payload, but zstd is not available here. "
            "On Python below 3.14 it comes from the 'backports.zstd' package."
        )

    return _zstd_decompress(data)


def encode_gltf(glb: bytes) -> bytes:
    """The payload a binary glTF buffer travels to the IDE viewer as: the buffer itself.

    Not compressed, unlike the BREP payloads above. It is on its way to the PartCAD
    IDE extension over a loopback socket, where zlib - which this used to be, at
    level 6 - cost two seconds of this process for a 25 MB assembly to take a third
    off a copy that costs milliseconds, and the extension then had to inflate it
    again. Bytes rather than text, so that this pipe carries it as bytes (see
    'encode()') and the viewer protocol as a blob; it is that protocol which decides
    how an IDE from before binary frames is sent it.

    The mirror of this function - the only other implementation - is
    'partcad_ide_client.protocol.encode_gltf'; the two have to stay in step.
    """
    return bytes(glb)


def _write_binary(shape, with_triangles: bool) -> bytes:
    with BytesIO() as bio:
        # Normals never: a surface gives them back exactly, and a face with no
        # surface keeps its own whatever this says (see BINARY_FORMAT_VERSION).
        OCP.BinTools.BinTools.Write_s(shape, bio, with_triangles, False, _binary_version)
        return bio.getvalue()


def _holds_mesh(payload: bytes) -> bool:
    """Whether a payload written without triangles still holds some: a face that is only a mesh.

    Read off the count in the header of the triangulation section, which is
    text in a binary payload. Looked for from the end: the section comes after
    "PolygonOnTriangulations", whose name ends in the same word, and before
    only the shapes themselves. A count that cannot be read answers yes, which
    costs a payload with its triangles in it and nothing else.
    """
    at = payload.rfind(_TRIANGULATIONS)
    if at < 0 or payload[max(at - 2, 0) : at] == b"On":
        return True
    start = at + len(_TRIANGULATIONS)
    end = payload.find(b"\n", start, start + 24)
    if end < 0:
        return True
    try:
        return int(payload[start:end]) != 0
    except ValueError:
        return True


def shape_to_brep(shape) -> bytes:
    """Serialize a TopoDS_Shape into the flat BREP byte array: binary, and without its mesh.

    Without its mesh because a triangulation is not geometry: it is what
    somebody meshed the faces to, at the tolerance they wanted, and every
    reader of a payload that needs one meshes for itself - a projection, an
    STL, a glTF and a CAE model each at their own tolerance (see
    'utils_ocp.tessellate', 'wrapper_gltf._mesh', 'render_svg'). Carried, it
    was most of the payload of anything that had been meshed: forty placements
    of the example motor, meshed, are 44 MB with it and 10 MB without (4.0 and
    1.2 MB compressed), written in 504 ms rather than 205.

    Except where it *is* the geometry: a face with no surface under it is its
    triangles - an SDF part, an STL read as a mesh, an imported glTF - and
    OCCT keeps those whatever it is told. What it does not keep, told to drop
    triangles, is the polygons on the edges bounding such a face, which are
    those edges' only geometry. So a shape found to hold a mesh is written
    again with everything, unless it has no edges for that to matter to (an
    SDF part is one face and no edge).

    Not covered: an edge whose only geometry is a 3D polygon, standing on its
    own. Nothing PartCAD reads or builds makes one, and telling would cost a
    walk over every edge of every shape - as long as writing it.

    ASCII where this OCP has no binary writer (an OCCT older than 7.6), which
    every reader still reads (see 'shape_from_brep()').
    """
    _ensure_ocp()
    if _binary_version is None:
        with BytesIO() as bio:
            OCP.BRepTools.BRepTools.Write_s(shape, bio)
            return bio.getvalue()

    payload = _write_binary(shape, False)
    if _holds_mesh(payload) and OCP.TopExp.TopExp_Explorer(shape, OCP.TopAbs.TopAbs_EDGE).More():
        payload = _write_binary(shape, True)
    return payload


def is_binary_brep(data) -> bool:
    """Whether a BREP payload (uncompressed) is OCCT's binary format rather than its ASCII one."""
    return bytes(data[:_SNIFF_WINDOW]).lstrip().startswith(BINARY_MAGIC)


def shape_from_brep(data: bytes):
    """Deserialize a flat BREP byte array into a downcast TopoDS_Shape.

    Either format, told apart by its header rather than by anything the
    envelope says: a payload written by an earlier release (in a shared cache
    tier, on the pipe from a peer), by Chili3D, whose kernel has an ASCII
    writer and no binary one, or read from a '.brep' file is ASCII, and every
    payload this module writes is binary.
    """
    _ensure_ocp()
    with BytesIO(data) as bio:
        shape = OCP.TopoDS.TopoDS_Shape()
        if is_binary_brep(data):
            OCP.BinTools.BinTools.Read_s(shape, bio)
        else:
            OCP.BRepTools.BRepTools.Read_s(shape, bio, OCP.BRep.BRep_Builder())
        return downcast(shape)


def shape_from_brep_file(path: str):
    """Read a '.brep' file in either format, as 'shape_from_brep()' reads a payload.

    A package's '.brep' is ASCII - that is what every tool writes by default -
    but one PartCAD wrote itself need not be: the volumes an interference check
    leaves behind are the payloads it answered with, decompressed into files
    (see 'partcad.test.interference_artifact'). The file is read by OCCT from
    its path rather than into memory first, and only its first bytes are read
    here.
    """
    _ensure_ocp()
    with open(path, "rb") as stream:
        head = stream.read(_SNIFF_WINDOW)
    shape = OCP.TopoDS.TopoDS_Shape()
    if is_binary_brep(head):
        read = OCP.BinTools.BinTools.Read_s(shape, path)
    else:
        read = OCP.BRepTools.BRepTools.Read_s(shape, path, OCP.BRep.BRep_Builder())
    if not read or shape.IsNull():
        raise ValueError("Failed to load BREP file: %s" % path)
    return shape


def compressed_brep(shape) -> bytes:
    """The zstd-compressed BREP bytes - how a shape payload is carried everywhere.

    Base64 is applied on top of this only where the payload has to travel as
    JSON; the core keeps the bytes (see partcad/shape_envelope.py).
    """
    return _compress(shape_to_brep(shape))


def _brep_b64(shape) -> str:
    return base64.b64encode(compressed_brep(shape)).decode("ascii")


def _brep_payload(value) -> bytes:
    """The compressed payload of a "brep" field, base64-encoded or raw.

    A payload that came off the pipe is base64 text; one handed over in-process
    (from a cache, say) is already the bytes, and is passed on without a copy.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return base64.b64decode(value)


def _shape_from_b64(brep_b64):
    return shape_from_brep(_decompress(_brep_payload(brep_b64)))


def payload_digest(value) -> str:
    """A stable name for one piece of exact geometry: a digest of its bytes.

    Of the compressed BREP as it arrived, not of anything derived from it, so that
    two nodes built from one cached shape are recognised as one geometry without
    either of them being decoded first - which is the whole point, since decoding
    and tessellating are what the sharing is meant to avoid.

    Content and not identity: nodes arrive as separately deserialized dicts, so the
    same geometry is the same bytes and never the same object.
    """
    return hashlib.sha256(_brep_payload(value)).hexdigest()


def shape_from_payload(value):
    """The TopoDS_Shape a node's "brep" field holds, however it travelled.

    Public because a wrapper handed an *undecoded* tree has to open its leaves
    itself: 'decode()' would rebuild the whole tree as one compound and drop the
    names, the placements and everything else the tree is for. See
    'wrapper_gltf.py' and 'wrapper_interference.py'.
    """
    return _shape_from_b64(value)


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


def make_metadata(measurements=None, annotations=None, sections=None):
    """A metadata dict holding whichever of the three sections has content.

    The sandbox-side twin of 'shape_envelope.make_metadata()'. Empty sections
    are left out rather than written empty, so that a wrapper which looked and
    found nothing produces no section at all - which is what lets a reader tell
    "this drawing annotates nothing" from "nobody has looked".
    """
    metadata = {}
    if measurements:
        metadata[METADATA_MEASUREMENTS] = measurements
    if annotations:
        metadata[METADATA_ANNOTATIONS] = list(annotations)
    if sections:
        metadata[METADATA_SECTIONS] = dict(sections)
    return metadata


def encode_shape(shape, name=None, label=None, metadata=None, measurer=None) -> dict:
    """Represent a single shape as {"name", "label", "brep", "metadata"}, ready for JSON.

    The shape is measured on the way through, and the numbers go into the
    'measurements' section of the envelope's metadata. This is the whole of how
    a part's size comes to be known: every wrapper that returns a shape returns
    it through here, this is the last point at which the live OCCT object
    exists, and the measuring is arithmetic over geometry that is already in
    memory and already being traversed to write its BREP.

    Measuring anywhere later means a second sandbox process, the BREP shipped
    back into it and deserialized, to compute what was free here.

    'metadata' is whatever the calling wrapper learnt that the geometry itself
    cannot answer - the sections a file stated about itself, the annotations it
    stated against individual elements. It is merged under the measurements
    rather than over them, because it comes from a wrapper that read a file
    while the measurements come from the geometry in hand, and on the one key
    they could share the geometry is the more recent truth.

    'measurer' is the 'shape_measure.Measurer' of the document this shape is
    part of, so that a solid it shares with another shape there is measured
    once; without one, the shape is measured on its own.
    """
    import shape_measure

    measured = (measurer or shape_measure.Measurer()).measurements_or_none(shape)
    combined = dict(metadata or {})
    if measured:
        combined[METADATA_MEASUREMENTS] = measured

    encoded = {"name": name, "label": label, KEY_BREP: _brep_b64(shape)}
    if combined:
        encoded[KEY_METADATA] = combined
    return encoded


def encode_assembly(children, name=None, label=None) -> dict:
    """Represent an assembly as {"name", "label", "assembly": [...]}.

    'children' is the already-encoded list of shape/assembly objects.
    """
    return {"name": name, "label": label, KEY_ASSEMBLY: list(children)}


def encode_combined(compound, components, name=None, label=None):
    """'compound' encoded, and 'components' as references into it: '(shape object, components)'.

    What 'wrapper_common.combine()' hands back is a compound and the shapes it
    was made of - the same geometry twice, since the compound holds those very
    shapes. Encoded as it stands, every component was written as a BREP of its
    own, measured again, sent at twice the size and cached again beside the
    compound. So a component the compound holds is encoded as a node naming
    the compound's payload and which child of it it is (KEY_CHILD), with the
    measurements its child already got as the compound was measured: written
    once, measured once, and - the payload being the one string - sent and
    cached once.

    A component the compound does not hold - a face a part's script returned
    beside its solids, which a part's compound leaves out - is encoded as a
    shape of its own, as before. 'components' keeps its nesting.
    """
    import shape_measure

    _ensure_ocp()
    measurer = shape_measure.Measurer()
    shape = encode_shape(compound, name=name, label=label, measurer=measurer)

    # Where each child sits in the compound, by what OCP hashes a shape by (its
    # 'TShape' and location); 'IsEqual()' then adds the orientation.
    children = {}
    iterator = OCP.TopoDS.TopoDS_Iterator(compound)
    index = 0
    while iterator.More():
        child = iterator.Value()
        children.setdefault(_shape_hash(child), []).append((child, index))
        index += 1
        iterator.Next()

    def refer(component):
        if isinstance(component, list):
            return [refer(item) for item in component]
        if isinstance(component, OCP.TopoDS.TopoDS_Shape) and not component.IsNull():
            for child, index in children.get(_shape_hash(component), ()):
                if child.IsEqual(component):
                    node = {"name": name, "label": label, KEY_BREP: shape[KEY_BREP], KEY_CHILD: index}
                    measured = measurer.measurements_or_none(child)
                    if measured:
                        node[KEY_METADATA] = {METADATA_MEASUREMENTS: measured}
                    return node
        return encode(component, name=name, label=label, measurer=measurer)

    return shape, refer(components)


def _shape_hash(shape):
    """What OCP hashes 'shape' by, or None for a build with no hash (every shape then collides)."""
    try:
        return hash(shape)
    except TypeError:
        return None


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def toploc_from_packed(packed):
    """Build a TopLoc_Location from the packed [[t], [axis], angle] location form.

    Public because a render implementation is handed locations in this form too
    (the ports "pc render --with-ports" draws), and there is no reason for it to
    reimplement the arithmetic.
    """
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
    return shape.Located(toploc_from_packed(packed))


def _shared_shape(payload, shared, child=None):
    """The shape a "brep" payload holds, read once however many nodes carry it.

    'shared' is the payloads already read in this decoding, and what each one
    was read into. An assembly is mostly repeats -- the LEGO castle is 731
    placements of 9 bricks -- and a placement was never part of the geometry,
    so every node carrying the same payload gets the same 'TShape' placed
    where that node says. That is what OCCT's own instancing is: whatever is
    computed on a shape is computed once per 'TShape', not once per placement,
    so meshing the castle meshes nine bricks rather than 731, and the
    hidden-line removal of a render works from nine triangulations. Decoded a
    node at a time, the castle's drawing took 3.4 GB; shared, 1.4 GB, and the
    picture is the same picture.

    Keyed by the payload itself, content and not identity -- the nodes arrive
    as separately parsed JSON, so the same geometry is the same text and never
    the same object -- and so two different shapes are never confused.

    Every node still gets a handle of its own: two nodes holding one Python
    object would be two nodes in which setting a location on one moved the
    other. The handle shares the 'TShape'; it is a new 'TopoDS_Shape' of the
    same type, at the same (empty) location.

    'child' is a node's KEY_CHILD: the shape handed back is then that child of
    the payload's shape, placed and oriented as the shape holds it. The
    payload is still read once, however many of its children are asked for.
    """
    key = payload if isinstance(payload, (str, bytes)) else bytes(payload)
    shape = shared.get(key)
    if shape is None:
        shape = shared[key] = _shape_from_b64(payload)
    if child is not None:
        # Keyed apart from every payload: a tuple is never a str or bytes.
        children = shared.get((key, KEY_CHILD))
        if children is None:
            children = []
            iterator = OCP.TopoDS.TopoDS_Iterator(shape)
            while iterator.More():
                children.append(iterator.Value())
                iterator.Next()
            shared[(key, KEY_CHILD)] = children
        if not isinstance(child, int) or isinstance(child, bool) or not 0 <= child < len(children):
            raise ValueError("A node names child %r of a shape that has %d" % (child, len(children)))
        shape = children[child]
    return downcast(shape.Located(shape.Location()))


def decode_shape(obj):
    """Turn a shape or assembly object back into OCCT geometry.

    A shape object yields its TopoDS_Shape; an assembly object yields a
    TopoDS_Compound of its children (recursively). An optional "location" field
    carried by either kind is applied here - the core builds the assembly tree
    with locations as plain data and never places geometry itself, so this is
    where a child's placement becomes an actual TopLoc. name/label are metadata.

    Nodes that carry the same payload share one 'TShape' (see '_shared_shape'),
    so an implementation must not modify a shape it is handed in place: with
    instancing, a change to one placement of a part is a change to all of them.
    """
    _ensure_ocp()
    return _decode_shape(obj, {})


def _decode_shape(obj, shared):
    if is_shape_object(obj):
        return _apply_location(_shared_shape(obj[KEY_BREP], shared, obj.get(KEY_CHILD)), obj.get(KEY_LOCATION))
    if is_assembly_object(obj):
        compound = compound_of(_decode_shape(child, shared) for child in obj[KEY_ASSEMBLY])
        return _apply_location(compound, obj.get(KEY_LOCATION))
    raise ValueError("Not a shape or assembly object: %r" % (list(obj) if isinstance(obj, dict) else type(obj)))


def decode_tree(obj, shared=None):
    """'decode_shape(obj)', and the tree it was decoded from, in one pass.

    Returns '(shape, tree)'. 'shape' is exactly what 'decode_shape(obj)' returns:
    the whole object as one piece of live geometry. 'tree' is 'obj' as it was -
    every node's name, label, location, properties, joint and metadata still
    there to be read as data - with every shape object also carrying its own
    geometry, decoded, under KEY_SHAPE.

    Both are built from the one decoding of each BREP, which is what makes
    handing out the two together cost no more than handing out the first. That
    is what 'wrapper_export' does for every implementation it runs: the
    geometry is what most of them write, and the tree is what says what each
    part of it *is* - which link of a robot, which colour - and decoding the
    geometry is exactly what throws that away.

    The nodes are copies; 'obj' is left as it was. Nodes carrying the same
    payload share one 'TShape', as 'decode_shape' says.

    'shared' is the payloads already read and what each was read into, for a
    caller that decodes several documents into one set of shapes and so reads
    each payload once across all of them (see 'wrapper_export.run_together').
    """
    _ensure_ocp()
    return _decode_tree(obj, {} if shared is None else shared)


def _decode_tree(obj, shared):
    if is_shape_object(obj):
        own = _shared_shape(obj[KEY_BREP], shared, obj.get(KEY_CHILD))
        node = dict(obj)
        node[KEY_SHAPE] = own
        return _apply_location(own, obj.get(KEY_LOCATION)), node
    if is_assembly_object(obj):
        decoded = [_decode_tree(child, shared) for child in obj[KEY_ASSEMBLY]]
        node = dict(obj)
        node[KEY_ASSEMBLY] = [child for _shape, child in decoded]
        compound = compound_of(shape for shape, _child in decoded)
        return _apply_location(compound, obj.get(KEY_LOCATION)), node
    raise ValueError("Not a shape or assembly object: %r" % (list(obj) if isinstance(obj, dict) else type(obj)))


def encode(obj, name=None, label=None, measurer=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    A TopoDS_Shape becomes a shape object. 'name'/'label', when given, are
    attached to every raw shape encoded - the wrapper protocol uses this to echo
    the name/label the request carried onto the single shape a response returns.
    An already-built shape/assembly object keeps its own name/label. Dicts,
    lists, tuples and sets are walked; exceptions become their message. A
    non-shape OCCT object (a Location/Axis a build123d script showed) drops to
    null - every consumer already discards it - and any other unknown type
    raises, to catch real bugs.

    Every JSON-native kind is settled before OCP is reached for, and that
    ordering is the point rather than tidiness. Importing OCP is the better part
    of a second - it is OpenCASCADE, several hundred megabytes of it - and the
    answers that carry no geometry at all are not rare: a repository plugin's
    reply is a dict of strings, and PartCAD asks a plugin one key at a time, in
    a process of its own, hundreds of times over to list a large package tree.
    Asking "is this dict a TopoDS_Shape?" first made every one of those calls
    load the kernel to find out it was not. A value only reaches _ensure_ocp()
    here when it is neither a scalar nor a container, which is the only way it
    could be OCCT.

    Every shape in 'obj' is measured with one 'shape_measure.Measurer' -
    'measurer', when the caller has one - so that a solid two of them share, a
    part shown twice or placed twice, is measured once.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if measurer is None:
        # Not the kernel: 'shape_measure' imports OCP only once it measures.
        import shape_measure

        measurer = shape_measure.Measurer()

    if isinstance(obj, dict):
        # An already-built shape/assembly object keeps its own metadata verbatim.
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            encoded = {}
            for key, value in obj.items():
                if key == KEY_BREP:
                    # Raw bytes reach here only in-process; on the pipe it is base64 already.
                    encoded[key] = value if isinstance(value, str) else base64.b64encode(value).decode("ascii")
                elif key == KEY_ASSEMBLY:
                    encoded[key] = [encode(child, name, label, measurer) for child in value]
                elif key in (KEY_LOCATION, "name", "label"):
                    encoded[key] = value
                else:
                    encoded[key] = encode(value, name, label, measurer)
            return encoded
        return {key: encode(value, name, label, measurer) for key, value in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item, name, label, measurer) for item in obj]

    if isinstance(obj, (bytes, bytearray)):
        return {KEY_BYTES: base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, BaseException):
        return str(obj)

    # Nothing JSON-native is left, so this is where the kernel is needed.
    _ensure_ocp()
    if isinstance(obj, OCP.TopoDS.TopoDS_Shape):
        return encode_shape(obj, name=name, label=label, measurer=measurer)

    if type(obj).__module__.split(".")[0] == "OCP":
        _warn("dropping non-shape OCCT object of type %s" % type(obj))
        return None

    raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))


def decode(obj, shared=None):
    """Inverse of 'encode()'.

    Every shape found anywhere in 'obj' is decoded as 'decode_shape' decodes a
    tree: the same payload twice -- two components of one request, two
    placements of a part -- is one 'TShape'. 'shared' is as 'decode_tree' has it.
    """
    return _decode(obj, {} if shared is None else shared)


def _decode(obj, shared):
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            _ensure_ocp()
            return _decode_shape(obj, shared)
        if KEY_BYTES in obj and len(obj) == 1:
            return base64.b64decode(obj[KEY_BYTES])
        return {key: _decode(value, shared) for key, value in obj.items()}

    if isinstance(obj, list):
        return [_decode(item, shared) for item in obj]

    return obj


def _shared_payloads(encoded):
    """'encoded' with each payload carried by more than one node written once, in a table.

    The answer of a wrapper that read a STEP assembly is a tree whose nodes are
    mostly the same few parts, each encoded separately into the same text. So the
    payloads are compared by value; when a table makes the document smaller,
    every node names its entry instead (KEY_BREP_REF) and the table goes on the
    top level (KEY_BREPS). When it does not, or 'encoded' is not a dict to put a
    table on, it is returned as it is, which keeps every answer that is not a
    tree of repeats the answer it always was. The rule is the core's, written out
    again here because a sandbox cannot import the core: see
    'shape_envelope.table_saves_space'.
    """
    if not isinstance(encoded, dict):
        return encoded
    counts = {}

    def count(obj):
        if isinstance(obj, dict):
            payload = obj.get(KEY_BREP)
            if isinstance(payload, str):
                counts[payload] = counts.get(payload, 0) + 1
            for value in obj.values():
                count(value)
        elif isinstance(obj, list):
            for item in obj:
                count(item)

    count(encoded)
    carried = sum(len(payload) * uses for payload, uses in counts.items())
    tabled = sum(len(payload) + _REFERENCE_COST + uses * _REFERENCE_COST for payload, uses in counts.items())
    if tabled >= carried:
        return encoded
    digests = {payload: payload_digest(payload) for payload in counts}

    def refer(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get(KEY_BREP), str):
                node = {key: refer(value) for key, value in obj.items() if key != KEY_BREP}
                node[KEY_BREP_REF] = digests[obj[KEY_BREP]]
                return node
            return {key: refer(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [refer(item) for item in obj]
        return obj

    shared = refer(encoded)
    shared[KEY_BREPS] = {digest: payload for payload, digest in digests.items()}
    return shared


def _inflate(document):
    """'document' with the payload table taken off it and each payload put back on its nodes.

    Every node naming one entry gets the same string object, so a payload read
    once is held once, and decoding it once per distinct payload ('_shared_shape')
    costs one dictionary lookup per node. A document without a table is returned
    as it is.
    """
    if not isinstance(document, dict) or KEY_BREPS not in document:
        return document
    table = document.pop(KEY_BREPS)

    def resolve(obj):
        if isinstance(obj, dict):
            if KEY_BREP_REF in obj:
                ref = obj[KEY_BREP_REF]
                if ref not in table:
                    raise ValueError("A shape names the payload %r, which the document does not carry" % (ref,))
                node = {key: resolve(value) for key, value in obj.items() if key != KEY_BREP_REF}
                node[KEY_BREP] = table[ref]
                return node
            return {key: resolve(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [resolve(item) for item in obj]
        return obj

    return resolve(document)


def dumps(obj, name=None, label=None, share=False) -> str:
    """Serialize 'obj' into a single-line JSON string.

    'share' writes a payload carried by more than one node once, in a table (see
    KEY_BREPS). Only a reader that knows the table may be handed it - which the
    core is, for every answer: 'shape_envelope.loads()' reads both forms.
    """
    encoded = encode(obj, name=name, label=label)
    return json.dumps(_shared_payloads(encoded) if share else encoded)


def loads(text) -> object:
    """Deserialize a JSON string produced by 'dumps()', or by 'shape_envelope.dumps()', with or without a table."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return decode(_inflate(json.loads(text)))


def serialize(obj, name=None, label=None, share=False) -> str:
    """Serialize 'obj' into the single-line form that travels over the pipe.

    Plain JSON, not base64-wrapped JSON: the JSON is already single-line and
    transport-safe (the BREP payload is base64), so an extra base64 layer would
    only cost time and ~1.3x size. See 'dumps()' for 'share'.
    """
    return dumps(obj, name=name, label=label, share=share)


def _payload_line(data) -> str:
    """The single JSON line carrying the payload.

    It is taken as the last non-empty line of 'data', so any leading progress a
    wrapper wrote to stdout is ignored.
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
    return line


def deserialize(data) -> object:
    """Deserialize the form produced by 'serialize()'."""
    return loads(_payload_line(data))


def deserialize_raw(data) -> object:
    """Deserialize without decoding shapes - envelopes stay as their dicts.

    The counterpart of the core-side 'shape_envelope.deserialize()', for the
    wrappers that need the *structure* of an assembly envelope rather than the
    geometry it decodes to: the URDF exporter names each link and places each
    joint from what the envelope says about a node, and 'decode()' keeps none of
    that - the compound it builds mirrors the tree, but the names and labels are
    gone and the placements are baked into the geometry.

    A document that carries its payloads in a table (KEY_BREPS) is handed back
    with each payload on the nodes naming it, as though it never had one.
    """
    return _inflate(json.loads(_payload_line(data)))
