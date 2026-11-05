#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to turn pieces of exact geometry from BREP into glTF.
#
# It is handed geometry and nothing else: a list of distinct BREP payloads, each
# under the digest the core names it by, and the deflection to tessellate them
# at. Not the tree they come from. The tree - the nodes, their names, their
# placements, the ports and interfaces each carries - is the same tree in either
# form (see 'partcad.shape_envelope'), so the core keeps it and puts the answer
# into it itself ('shape_gltf.convert_async'); only what sits at a node that has
# geometry changes, and that is all that is computed here. Which is also what
# lets the core remember each tessellation on its own, and send this process only
# the geometry it has not tessellated before: edit one part of an assembly and
# one part is tessellated again.
#
# One process for all of them, not one per shape. Tessellating is a fraction of
# what a sandbox costs - starting an interpreter and importing OCP is seconds -
# so an assembly of five hundred parts converted a part at a time would take
# longer than building it did.
#
# The glTF of a shape is its geometry in its own coordinate system. The tree
# carries placements as data and applies them where the tree is realized (see
# 'ocp_serialize.decode_shape', which does it for the BREP form), and whoever
# draws the tree composes the locations down it; a sketch a port is drawn with is
# placed at the port the same way.

import hashlib
import json
import os
import struct
import sys
import tempfile

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import appearance
import ocp_serialize
import texture_mapping
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# What is handed to export_gltf's own deflection argument once the shape has been
# meshed here. It is not a deflection: it is "whatever is already triangulated is
# fine", which is how export_gltf is told to leave the mesh alone. See _to_glb.
_ALREADY_MESHED = 1e9


def _mesh(shape, tolerance, angular_tolerance):
    """Triangulate 'shape' to an absolute linear deflection, in mm.

    This is here rather than left to export_gltf because export_gltf asks OCCT for
    a *relative* deflection: it calls Shape.mesh(), which passes isRelative=True to
    BRepMesh_IncrementalMesh, and the number then means a fraction of the size of
    each edge rather than a distance. Per-edge is the wrong scale for something
    that is looked at as a whole - it holds a 3 mm hole to the same fraction of
    3 mm whether the assembly around it is 30 mm or 30 m, so the small features of
    a large assembly are tessellated as finely as if they filled the screen.

    Meshing first is what lets an absolute deflection stand: export_gltf skips its
    own meshing for a shape that already carries a triangulation fine enough for
    the deflection it is given, so it is handed _ALREADY_MESHED and leaves this
    one alone. 'test_shape_gltf.py' holds that arrangement in place - if a
    build123d release ever re-meshed regardless, the triangle count would stop
    responding to the tolerance and nothing else would say so.
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools

    BRepTools.Clean_s(shape)
    BRepMesh_IncrementalMesh(shape, tolerance, False, angular_tolerance, True)


# build123d's builder for the document OCCT's glTF writer writes, resolved on
# first use: False until it has been looked for, then it or None. Looked up rather
# than imported at the top because importing build123d is what costs, and this
# file is imported by tests that never export anything.
_create_xde = False


def _xde_builder():
    """build123d's XCAF document builder, or None if this release has none.

    Private to build123d, and the one piece of it that has to be reached for: see
    '_write_merged' for what driving the writer directly buys and what is given up
    when this is absent.
    """
    global _create_xde
    if _create_xde is False:
        try:
            from build123d.exporters3d import _create_xde as builder
        except Exception:
            builder = None
        _create_xde = builder
    return _create_xde


def _write_merged(obj, path, builder) -> bool:
    """Write 'obj' to 'path' as a binary glTF of one primitive per shape.

    Which is the whole reason the writer is driven here rather than through
    'build123d.export_gltf': a glTF loader makes a mesh per primitive and a mesh is
    a draw call, OCCT writes a primitive per *face* by default, and a part of fifty
    faces is therefore fifty draw calls - a fifty-part assembly two and a half
    thousand, which is what makes one slow to orbit however few triangles it has.
    'SetMergeFaces' concatenates them into one, losslessly: the triangles and their
    vertices are copied rather than welded, so the shading is identical and only the
    grouping differs.

    Everything else here is export_gltf's, deliberately. The document is built by
    the same helper, and the rotation is the same one it applies - OCCT is Z up and
    glTF is Y up, and whoever draws the result undoes exactly this (see
    'frames.ts'), so the two must not drift apart.
    """
    import build123d as b3d
    from OCP.BRepTools import BRepTools
    from OCP.Message import Message, Message_Gravity, Message_ProgressRange
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    from OCP.TCollection import TCollection_AsciiString

    original = obj.location
    obj.location *= b3d.Location((0, 0, 0), (1, 0, 0), -90)
    try:
        doc = builder(obj, b3d.Unit.MM, auto_naming=False)
        # OCCT reports progress and warnings through the default messenger, which
        # prints to this process's stdout - and stdout is how a wrapper answers.
        for printer in Message.DefaultMessenger_s().Printers():
            printer.SetTraceLevel(Message_Gravity.Message_Fail)
        writer = RWGltf_CafWriter(TCollection_AsciiString(path), True)
        writer.SetParallel(True)
        writer.SetMergeFaces(True)
        return bool(writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()))
    finally:
        obj.location = original
        BRepTools.Clean_s(obj.wrapped)


def _colored(shape, colors):
    """'shape' as build123d draws it in colours: a child per colour, each the faces drawn in it.

    'colors' is a colour (or None) per face, from the shape's CMF section (see
    'appearance.section_face_colors'). glTF has no colour per face, only a
    material per primitive, so the faces of one colour are made one child and
    the colour is put on that child - the one way of saying it the writer reads
    (see '_write_merged') - and what comes out is a mesh per colour, each with
    its material, in place of the one mesh an uncoloured shape is. The faces are
    the shape's own, already triangulated; nothing is meshed again.
    """
    import build123d as b3d

    children = []
    for color, piece in appearance.faces_by_color(shape, colors, None):
        child = b3d.Compound(piece)
        if color is not None:
            red, green, blue, alpha = appearance.parse(color)
            child.color = b3d.Color(red / 255.0, green / 255.0, blue / 255.0, alpha)
        children.append(child)
    return b3d.Compound(children=children)


def _export(shape, angular_tolerance, colors=None):
    """The binary glTF of 'shape' as it is already triangulated.

    One primitive per shape where that can be asked for (see '_write_merged'), and
    export_gltf's one per face where it cannot - a preview that is slow to orbit
    rather than no preview at all. Nothing downstream assumes which happened;
    'test_shape_gltf.py' counts the primitives, so a build123d release that moved
    the document builder fails there rather than in someone's frame rate.

    Deliberately does no meshing of its own - see _mesh, which is the half of this
    that decides how fine the result is. Separate so that it is possible to ask what
    one deflection or another produces, which is what 'test_shape_gltf.py' does.
    """
    import build123d as b3d

    # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract, so
    # it silently returns None and export_gltf then fails on None.location.
    obj = _colored(shape, colors) if colors else b3d.Compound.cast(ocp_serialize.compound_of([shape]))

    # The writer only writes to a path, so the buffer has to come back off the
    # disk. A temp file rather than the shape's render output: this is a preview,
    # not a render, and must not leave artifacts in the package directory.
    handle, path = tempfile.mkstemp(suffix=".glb", prefix="partcad-gltf-")
    os.close(handle)
    try:
        builder = _xde_builder()
        if builder is None or not _write_merged(obj, path, builder):
            b3d.export_gltf(
                obj,
                path,
                binary=True,
                linear_deflection=_ALREADY_MESHED,
                angular_deflection=angular_tolerance,
            )
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception("the exporter produced no glTF")
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# The glTF constants the line primitive below is written with: the component type
# of a 32-bit float, the target of a vertex buffer, and the 'LINES' draw mode (each
# consecutive pair of positions is one segment).
_GLTF_FLOAT = 5126
_GLTF_ARRAY_BUFFER = 34962
_GLTF_LINES = 1

# And the ones a textured primitive adds: indices as 32-bit unsigned integers in
# an index buffer, drawn as 'TRIANGLES'; and an image sampled between its pixels,
# from the size of it the view needs, repeated both ways ('REPEAT', since an image
# is laid on a surface in copies side by side - see 'texture_mapping').
_GLTF_UNSIGNED_INT = 5125
_GLTF_ELEMENT_ARRAY_BUFFER = 34963
_GLTF_TRIANGLES = 4
_GLTF_LINEAR = 9729
_GLTF_LINEAR_MIPMAP_LINEAR = 9987
_GLTF_REPEAT = 10497

# The two chunk types of a binary glTF, as the little-endian integers they are
# written as: b"JSON" and b"BIN\0".
_GLB_JSON = 0x4E4F534A
_GLB_BIN = 0x004E4942


def _has_faces(shape) -> bool:
    """Whether 'shape' holds a face - which is what export_gltf is able to write."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    return TopExp_Explorer(shape, TopAbs_FACE).More()


def _free_edges(shape) -> list:
    """The edges of 'shape' that bound no face.

    What a sketch of open lines is made of - the bend lines of a sheet metal
    drawing, a centre line, a path - and what glTF's triangles have no way to
    carry, so export_gltf drops them without a word. The edges of a face are not
    among them: the face already draws its outline, and a part would otherwise be
    drawn as a wireframe over itself.
    """
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
    edges = []
    for index in range(1, ancestors.Extent() + 1):
        if ancestors.FindFromIndex(index).Size() > 0:
            continue
        edge = TopoDS.Edge_s(ancestors.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        edges.append(edge)
    return edges


def _segments(edges, tolerance, angular_tolerance) -> list:
    """'edges' as line segments, in glTF's frame: a flat list of x, y, z floats.

    Discretized to the same deflection the faces are meshed to, so that a curve
    drawn as a line is as smooth as the same curve drawn as the rim of a face.
    Converted the way export_gltf converts what it writes - millimetres to metres,
    Z up to Y up - because these go into the same file as its triangles and the
    viewer converts neither (see 'frames.ts').
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_TangentialDeflection

    positions = []
    for edge in edges:
        try:
            points = GCPnts_TangentialDeflection(BRepAdaptor_Curve(edge), angular_tolerance, tolerance)
        except Exception:
            continue
        previous = None
        for index in range(1, points.NbPoints() + 1):
            point = points.Value(index)
            # PartCAD's (x, y, z) mm is glTF's (x, z, -y) m: a rotation of -90
            # degrees about X, which is what export_gltf applies to the shape.
            current = (point.X() / 1000.0, point.Z() / 1000.0, -point.Y() / 1000.0)
            if previous is not None:
                positions.extend(previous)
                positions.extend(current)
            previous = current
    return positions


def _read_glb(glb: bytes):
    """The JSON and the binary chunk of a binary glTF, as (dict, bytes)."""
    magic, _, length = struct.unpack_from("<III", glb, 0)
    if magic != 0x46546C67:
        raise Exception("not a binary glTF")
    meta, binary = None, b""
    offset = 12
    while offset < length:
        size, kind = struct.unpack_from("<II", glb, offset)
        data = glb[offset + 8 : offset + 8 + size]
        if kind == _GLB_JSON:
            meta = json.loads(data.decode("utf-8"))
        elif kind == _GLB_BIN:
            binary = bytes(data)
        offset += 8 + size
    if meta is None:
        raise Exception("a binary glTF with no JSON chunk")
    return meta, binary


def _write_glb(meta: dict, binary: bytes) -> bytes:
    """A binary glTF of this JSON and this binary chunk, each padded as the spec asks."""
    text = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(text), _GLB_JSON) + text
    if binary:
        chunks += struct.pack("<II", len(binary), _GLB_BIN) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def _with_lines(glb, positions) -> bytes:
    """'glb' with one more node, drawing 'positions' as line segments.

    'glb' is what export_gltf wrote, or None when there was nothing for it to
    write - a sketch of open lines has no face - in which case the file is
    started from nothing. The segments go into a mesh of their own, one 'LINES'
    primitive in the scene's own frame, beside whatever the file already draws:
    a viewer's glTF loader makes line segments out of it, and anything reading
    only the triangles of a file sees exactly the triangles it saw before.
    """
    if glb:
        meta, binary = _read_glb(glb)
    else:
        meta = {"asset": {"version": "2.0", "generator": "PartCAD"}, "scene": 0, "scenes": [{"nodes": []}]}
        binary = b""

    binary += b"\0" * (-len(binary) % 4)
    offset = len(binary)
    data = struct.pack("<%df" % len(positions), *positions)
    binary += data

    buffers = meta.setdefault("buffers", [])
    if buffers:
        buffers[0]["byteLength"] = len(binary)
    else:
        buffers.append({"byteLength": len(binary)})

    views = meta.setdefault("bufferViews", [])
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": _GLTF_ARRAY_BUFFER})

    # 'min' and 'max' are required of a POSITION accessor, and are what a loader
    # takes the bounds of the geometry from.
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
    accessors = meta.setdefault("accessors", [])
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": _GLTF_FLOAT,
            "count": len(positions) // 3,
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        }
    )

    meshes = meta.setdefault("meshes", [])
    meshes.append(
        {"name": "edges", "primitives": [{"attributes": {"POSITION": len(accessors) - 1}, "mode": _GLTF_LINES}]}
    )
    nodes = meta.setdefault("nodes", [])
    nodes.append({"name": "edges", "mesh": len(meshes) - 1})
    scenes = meta.setdefault("scenes", [{"nodes": []}])
    scenes[meta.get("scene", 0)].setdefault("nodes", []).append(len(nodes) - 1)
    return _write_glb(meta, binary)


def _face_triangles(shape):
    """Every face of 'shape' as it is already meshed: '(points, normals, corners)' in its own frame, in mm.

    'points' and 'normals' (N, 3), a normal pointing out of the material at
    every point, and 'corners' (M, 3) indices wound counter-clockwise seen from
    outside - what glTF draws as the front of a triangle. Each face keeps its own
    points, so that its edges stay sharp, as the faces OCCT's writer writes do.
    """
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    points, normals, corners = [], [], []
    offset = 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, location)
        if poly is None or poly.NbTriangles() == 0:
            continue
        if not poly.HasNormals():
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, poly)
        count = poly.NbNodes()
        transform = location.Transformation()
        nodes, directions = [], []
        for index in range(1, count + 1):
            point = poly.Node(index).Transformed(transform)
            nodes.append((point.X(), point.Y(), point.Z()))
            normal = poly.Normal(index)
            normal.Transform(transform)
            directions.append((normal.X(), normal.Y(), normal.Z()))
        indices = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
        directions = np.array(directions, dtype=np.float64)
        if face.Orientation() == TopAbs_REVERSED:
            directions = -directions
            indices = indices[:, [0, 2, 1]]
        points.append(np.array(nodes, dtype=np.float64))
        normals.append(directions)
        corners.append(indices + offset)
        offset += count
    if not points:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    normals = np.concatenate(normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return np.concatenate(points), normals / np.where(lengths > 0, lengths, 1.0), np.concatenate(corners)


def _textured_mesh(shape, texture):
    """The triangles of 'shape' with the image laid on them: '(positions, normals, texcoords, indices)'.

    In glTF's frame, as '_segments' writes lines: metres, Y up. A point shared
    by triangles that lie on different sides of the image's box is one vertex
    per side (see 'texture_mapping.box_uv'), and one vertex otherwise.
    """
    import numpy as np

    points, normals, corners = _face_triangles(shape)
    if not len(corners):
        return None
    uv = texture_mapping.gltf_texcoords(texture_mapping.box_uv(points, corners, texture.width, texture.height))
    keys = np.concatenate([corners.reshape(-1, 1).astype(np.float64), uv.reshape(-1, 2)], axis=1)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    point_index = unique[:, 0].astype(np.int64)
    position = points[point_index]
    normal = normals[point_index]
    # PartCAD's (x, y, z) mm is glTF's (x, z, -y) m, as in '_segments'.
    position = np.stack([position[:, 0], position[:, 2], -position[:, 1]], axis=1) / 1000.0
    normal = np.stack([normal[:, 0], normal[:, 2], -normal[:, 1]], axis=1)
    return (
        position.astype("<f4"),
        normal.astype("<f4"),
        unique[:, 1:3].astype("<f4"),
        np.asarray(inverse, dtype="<u4").reshape(-1),
    )


def _with_textures(glb, groups):
    """'glb' with a mesh for each of 'groups', each drawn with its image; started from nothing if 'glb' is None.

    'groups' is '[(colour, texture, mesh), ...]': the faces of a shape drawn
    with one image, as 'appearance.faces_by_look' gathers them, as
    '_textured_mesh' made them ready to write. None for no groups. Each is one
    primitive whose material has the image as its base colour, white under it
    (glTF multiplies the two), and the image itself is in the file once however
    many primitives draw with it - the bytes the colour's declaration names, PNG
    or JPEG, as glTF carries either. Laid on as everything else that draws one
    lays it ('texture_mapping'), so that the IDE shows what a shaded picture
    does. The colour drawn as where an image cannot be is in the material's
    'extras', for a reader that wants it.
    """
    if not groups:
        return glb
    if glb:
        meta, binary = _read_glb(glb)
    else:
        meta = {"asset": {"version": "2.0", "generator": "PartCAD"}, "scene": 0, "scenes": [{"nodes": []}]}
        binary = b""
    binary = bytearray(binary)
    views = meta.setdefault("bufferViews", [])
    accessors = meta.setdefault("accessors", [])

    def view(data: bytes, target=None) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        entry = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
        if target is not None:
            entry["target"] = target
        binary.extend(data)
        views.append(entry)
        return len(views) - 1

    def accessor(array, kind, component, target, bounds=False) -> int:
        entry = {
            "bufferView": view(array.tobytes(), target),
            "componentType": component,
            "count": int(array.shape[0]) if kind != "SCALAR" else int(array.size),
            "type": kind,
        }
        if bounds:
            entry["min"] = [float(v) for v in array.min(axis=0)]
            entry["max"] = [float(v) for v in array.max(axis=0)]
        accessors.append(entry)
        return len(accessors) - 1

    images = meta.setdefault("images", [])
    textures = meta.setdefault("textures", [])
    samplers = meta.setdefault("samplers", [])
    materials = meta.setdefault("materials", [])
    meshes = meta.setdefault("meshes", [])
    nodes = meta.setdefault("nodes", [])
    scene_nodes = meta.setdefault("scenes", [{"nodes": []}])[meta.get("scene", 0)].setdefault("nodes", [])
    samplers.append(
        {
            "magFilter": _GLTF_LINEAR,
            "minFilter": _GLTF_LINEAR_MIPMAP_LINEAR,
            "wrapS": _GLTF_REPEAT,
            "wrapT": _GLTF_REPEAT,
        }
    )
    sampler = len(samplers) - 1
    image_of = {}
    for color, texture, mesh in groups:
        position, normal, texcoord, indices = mesh
        if texture.digest not in image_of:
            images.append({"bufferView": view(texture.image), "mimeType": texture.mime_type or "image/png"})
            textures.append({"sampler": sampler, "source": len(images) - 1})
            image_of[texture.digest] = len(textures) - 1
        parsed = appearance.parse(color) if color is not None else None
        alpha = parsed[3] if parsed is not None else 1.0
        material = {
            "name": texture.name or "texture",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, alpha],
                "baseColorTexture": {"index": image_of[texture.digest]},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "extras": {"partcadColor": color},
        }
        if alpha < 1.0:
            material["alphaMode"] = "BLEND"
        materials.append(material)
        primitive = {
            "attributes": {
                "POSITION": accessor(position, "VEC3", _GLTF_FLOAT, _GLTF_ARRAY_BUFFER, bounds=True),
                "NORMAL": accessor(normal, "VEC3", _GLTF_FLOAT, _GLTF_ARRAY_BUFFER),
                "TEXCOORD_0": accessor(texcoord, "VEC2", _GLTF_FLOAT, _GLTF_ARRAY_BUFFER),
            },
            "indices": accessor(indices, "SCALAR", _GLTF_UNSIGNED_INT, _GLTF_ELEMENT_ARRAY_BUFFER),
            "material": len(materials) - 1,
            "mode": _GLTF_TRIANGLES,
        }
        meshes.append({"name": texture.name or "texture", "primitives": [primitive]})
        nodes.append({"name": texture.name or "texture", "mesh": len(meshes) - 1})
        scene_nodes.append(len(nodes) - 1)
    buffers = meta.setdefault("buffers", [])
    if buffers:
        buffers[0]["byteLength"] = len(binary)
    else:
        buffers.append({"byteLength": len(binary)})
    return _write_glb(meta, bytes(binary))


def _draws_lines(glb: bytes) -> bool:
    """Whether export_gltf already wrote line segments into 'glb'.

    OCCT's writer does write the free edges of a shape that also has faces, as a
    'LINES' primitive beside the triangles - and writes nothing at all for a shape
    that has only edges. Which is the gap '_with_lines' fills, and it fills only
    that one: adding the same edges a second time would draw each twice.
    """
    meta, _ = _read_glb(glb)
    return any(
        primitive.get("mode") == _GLTF_LINES
        for mesh in meta.get("meshes", [])
        for primitive in mesh.get("primitives", [])
    )


class NothingToDraw(Exception):
    """A shape with no face and no edge: a point, an empty compound.

    Told apart from every other reason a shape comes back without glTF because it
    is a fact about the geometry and nothing else - the same payload has nothing
    to draw on every machine, every time - so it is an answer the core may
    remember, where a decoder or an exporter failing may be this sandbox's doing
    (see 'shape_gltf.convert_async').
    """


def _to_glb(shape, tolerance, angular_tolerance, colors=None, looks=None):
    """Tessellate one shape into a binary glTF buffer, at an absolute deflection.

    Faces become triangles and the edges that bound no face become line segments,
    so that a sketch of open lines is drawn rather than dropped: glTF can carry
    both, and export_gltf writes the second only beside the first. A shape with neither - a point,
    an empty compound - is reported rather than sent as a file that draws nothing.

    'colors' is a colour per face where the shape's CMF section colours its faces
    one by one (see '_colored'), and None - the shape in one piece, as always -
    everywhere else.

    'looks' is what 'appearance.payload_looks' answers where the section draws
    any face with an image, and None everywhere else. The faces drawn with one
    are written by '_with_textures', which lays the image on them; the rest go
    through OCCT's writer as they would have, coloured as 'colors' says.
    """
    _mesh(shape, tolerance, angular_tolerance)
    glb = None
    if looks is not None:
        textured, shape_rest, colors = _split_textured(shape, looks)
        # Read off the faces before the rest is written: writing it cleans the
        # meshes of what it writes, and nothing here is meshed again.
        meshes = [(color, texture, _textured_mesh(piece, texture)) for color, texture, piece in textured]
        if shape_rest is not None and _has_faces(shape_rest):
            glb = _export(shape_rest, angular_tolerance, colors)
        glb = _with_textures(glb, [entry for entry in meshes if entry[2] is not None])
    elif _has_faces(shape):
        glb = _export(shape, angular_tolerance, colors)
    if glb is None or not _draws_lines(glb):
        positions = _segments(_free_edges(shape), tolerance, angular_tolerance)
        if positions:
            glb = _with_lines(glb, positions)
    if glb is None:
        raise NothingToDraw("there are no faces or edges to draw")
    return glb


def _split_textured(shape, looks):
    """'(textured, rest, colors)': 'shape''s faces drawn with an image, and the others.

    'textured' is '[(colour, texture, faces), ...]', one entry per image; 'rest'
    is a compound of every other face - None where there is none - and 'colors'
    a colour per face of it, in its own order, or None where none is coloured.
    """
    if looks[0] == appearance.WHOLE:
        color, texture = looks[1]
        return [(color, texture, shape)], None, None
    textured, others = [], []
    for (color, texture), piece in appearance.faces_by_look(shape, looks[1], (None, None)):
        if texture is not None:
            textured.append((color, texture, piece))
        else:
            others.append((color, piece))
    if not others:
        return textured, None, None
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    faces, colors = [], []
    for color, piece in others:
        explorer = TopExp_Explorer(piece, TopAbs_FACE)
        while explorer.More():
            faces.append(explorer.Current())
            colors.append(color)
            explorer.Next()
    if not faces:
        return textured, None, None
    return textured, ocp_serialize.compound_of(faces), colors if any(colors) else None


def process(request):
    """The glTF of every shape in 'request', by the digest the core named each one by.

    'shapes' is a list of '{"digest", "brep"}', one per distinct payload: the core
    has already found which of a tree's shapes are the same shape, and which of
    them it tessellated before, so nothing here is decoded or tessellated twice and
    nothing is recomputed to name it. What comes back is keyed by those same
    digests, in one of three tables: 'geometry' for the glTF of each shape that has
    some, 'empty' for a shape with nothing to draw ('NothingToDraw'), and 'failed'
    for one that would not tessellate - each with the reason, which the core
    reports against the nodes it belongs to. A shape that fails costs its own
    entry and nothing else: the rest of the tree is still worth looking at.
    """
    shapes = request.get("shapes")
    if not isinstance(shapes, list):
        raise Exception("No shapes to convert into glTF")
    # In millimetres, and decided by the caller. Not worked out here, although this
    # is the one process holding a kernel: the size it would be worked out from is
    # recorded in the tree, the core reads it from there ('shape_gltf.size_of'), and
    # measuring it again here would be a second answer to one question.
    tolerance = request.get("tolerance")
    if tolerance is None:
        raise Exception("No tolerance to tessellate at; the caller decides it (see 'shape_gltf.tolerance_for')")
    tolerance = float(tolerance)
    angular_tolerance = float(request.get("angularTolerance", 0.4))

    geometry, empty, failed = {}, {}, {}
    for entry in shapes:
        digest = entry.get("digest")
        try:
            shape = ocp_serialize.shape_from_payload(entry[ocp_serialize.KEY_BREP])
            # A payload is one piece of geometry with whatever CMF it carries, so
            # what a face is drawn in is the payload's to say, and comes back
            # under its digest like the rest. No output changes for a payload
            # with no face-by-face section, which every payload written before
            # sections existed is - so nothing tessellated before is stale, and
            # CACHE_VERSION stays.
            #
            # The image a colour is drawn with too (see '_with_textures'): a
            # payload carrying one is new, so nothing tessellated before draws
            # one and CACHE_VERSION stays for that as well.
            section = ocp_serialize.cmf_of_payload(entry[ocp_serialize.KEY_BREP])
            colors = appearance.section_face_colors(section)
            looks = appearance.payload_looks(section)
            geometry[digest] = ocp_serialize.encode_gltf(_to_glb(shape, tolerance, angular_tolerance, colors, looks))
        except NothingToDraw as e:
            empty[digest] = str(e)
        except Exception as e:
            failed[digest] = str(e) or type(e).__name__
    return {
        "success": True,
        "exception": None,
        "geometry": geometry,
        "empty": empty,
        "failed": failed,
        # What was used, so that the core can say so rather than leave the numbers
        # that decide the size of all this unsaid. 'mergedFaces' is None when
        # nothing was exported and so nothing was found out.
        "tolerance": tolerance,
        "angularTolerance": angular_tolerance,
        "mergedFaces": None if _create_xde is False else (_create_xde is not None),
    }


if __name__ == "__main__":
    # The shapes arrive undecoded, as the dicts they travelled in: decoding would
    # turn each into a live shape and drop the digest beside it, which is the
    # name the answer has to come back under. 'process' decodes them one by one.
    #
    # The path argv[1] carries is unused: the glTF comes back over the pipe
    # rather than as a file. handle_input() requires the argument all the same,
    # so the caller passes the operation name there.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        model = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
