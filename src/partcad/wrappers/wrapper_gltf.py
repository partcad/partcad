#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to turn a shape tree's geometry from BREP into glTF.
#
# It is the same tree either way - the nodes, their names, their placements, the
# ports and interfaces each carries - with one payload swapped for the other:
# 'brep' becomes 'gltf'. Which is the whole point of having two forms (see
# 'partcad.shape_envelope'): the core composes and caches the exact form, and a
# renderer can only draw a tessellated one. A browser has no CAD kernel, so the
# conversion cannot happen there; the core has none either, so it cannot happen
# there; it happens here.
#
# One process for the whole tree, not one per leaf. Tessellating is a fraction of
# what a sandbox costs - starting an interpreter and importing OCP is seconds -
# so an assembly of five hundred parts converted a part at a time would take
# longer than building it did.
#
# A node's own placement is left exactly where it was found. The tree carries
# placements as data and applies them where the tree is realized (see
# 'ocp_serialize.decode_shape', which does it for the BREP form); so the glTF of
# a node is its geometry in its own coordinate system, and whoever draws the tree
# composes the locations down it. The same goes for a sketch a port is drawn with:
# it arrives in its own coordinate system and is placed at the port by whoever
# draws it.

import hashlib
import json
import math
import os
import struct
import sys
import tempfile

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

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


def _export(shape, angular_tolerance):
    """The binary glTF of 'shape' as it is already triangulated.

    Deliberately does no meshing of its own - see _mesh, which is the half of this
    that decides how fine the result is. Separate so that it is possible to ask what
    one deflection or another produces, which is what 'test_shape_gltf.py' does.
    """
    import build123d as b3d

    # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract, so
    # it silently returns None and export_gltf then fails on None.location.
    obj = b3d.Compound.cast(ocp_serialize.compound_of([shape]))

    # export_gltf only writes to a path, so the buffer has to come back off the
    # disk. A temp file rather than the shape's render output: this is a preview,
    # not a render, and must not leave artifacts in the package directory.
    handle, path = tempfile.mkstemp(suffix=".glb", prefix="partcad-gltf-")
    os.close(handle)
    try:
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


def _to_glb(shape, tolerance, angular_tolerance):
    """Tessellate one shape into a binary glTF buffer, at an absolute deflection.

    Faces become triangles and the edges that bound no face become line segments,
    so that a sketch of open lines is drawn rather than dropped: glTF can carry
    both, and export_gltf writes the second only beside the first. A shape with neither - a point,
    an empty compound - is reported rather than sent as a file that draws nothing.
    """
    _mesh(shape, tolerance, angular_tolerance)
    glb = _export(shape, angular_tolerance) if _has_faces(shape) else None
    if glb is None or not _draws_lines(glb):
        positions = _segments(_free_edges(shape), tolerance, angular_tolerance)
        if positions:
            glb = _with_lines(glb, positions)
    if glb is None:
        raise Exception("there are no faces or edges to draw")
    return glb


def _shape(brep, shapes):
    """The decoded shape for this payload, decoded once however often it turns up."""
    digest = ocp_serialize.payload_digest(brep)
    if digest not in shapes:
        shapes[digest] = ocp_serialize.shape_from_payload(brep)
    return digest, shapes[digest]


def _size(tree, shapes, errors):
    """The diagonal of the whole tree's bounding box, in mm, or None if it has none.

    The placements are composed on the way down, because that is what decides how
    big the thing on the screen is: eight parts 50 mm across are 50 mm if they sit
    on top of each other and 2 m if they are spread out, and the deflection that
    looks right differs by the same factor. Composed the way the tree states it -
    the placement being applied first, then the node's own - so that this agrees
    with 'shape_envelope.placed()' and with whoever draws the result.

    Only the nodes. The sketches a port is drawn with sit at a port, which is inside
    the object whose port it is, so they cannot make the tree bigger than its nodes
    already make it.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()

    def walk(node, location):
        if not isinstance(node, dict):
            return
        own = node.get(ocp_serialize.KEY_LOCATION)
        if own is None:
            here = location
        else:
            placement = ocp_serialize.toploc_from_packed(own)
            here = placement if location is None else location.Multiplied(placement)
        brep = node.get(ocp_serialize.KEY_BREP)
        if brep:
            try:
                _, shape = _shape(brep, shapes)
                # 'Moved' shares the underlying geometry rather than copying it, so
                # measuring where a node sits costs nothing beyond the box itself.
                BRepBndLib.Add_s(shape if here is None else shape.Moved(here), box, True)
            except Exception as e:
                errors.append("%s: %s" % (node.get("label") or node.get("name") or "a shape", e))
        for child in node.get(ocp_serialize.KEY_ASSEMBLY) or []:
            walk(child, here)

    walk(tree, None)
    if box.IsVoid():
        return None
    x0, y0, z0, x1, y1, z1 = box.Get()
    return math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)


def _budget(size, request):
    """The linear deflection to tessellate at, in mm.

    Either what the caller asked for outright, or the screen-space budget the core
    sent worked out against the size measured above. Clamped at both ends: the floor
    stops a tiny object being tessellated to death for a gain no screen can show,
    and the ceiling stops one stray node far from the origin turning everything else
    into facets.
    """
    asked = request.get("tolerance")
    if asked is not None:
        return float(asked)
    floor = float(request.get("minTolerance", 0.001))
    ceiling = float(request.get("maxTolerance", 10.0))
    divisor = float(request.get("screenDivisor") or 0.0)
    if not size or divisor <= 0.0:
        return floor
    return min(max(size / divisor, floor), ceiling)


def _convert(value, tolerance, angular_tolerance, errors, shapes, geometry, failed):
    """'value' with every piece of BREP in it replaced by a reference to its glTF.

    A walk of the whole structure rather than of the places a node's geometry is
    known to sit. Geometry turns up in more than one of them - a node's own, the
    nodes inside it, the sketches the ports of an object are drawn with - and which
    ones those are is the core's business: it adds one without telling this file,
    and a walk that knew the list would quietly hand the browser BREP the day it
    did. Anything that is not geometry is copied through untouched.

    The glTF itself goes into 'geometry', keyed by a digest of the exact geometry it
    was made from, and what had the BREP gets that key. So one shape placed a
    hundred times is tessellated once, and the answer carries one copy of it: the
    placements are what differ between those hundred nodes, and placements are not
    in the geometry.

    A shape that will not tessellate loses its geometry and keeps its place, with
    the reason collected for the caller to report - once per distinct shape rather
    than once per node that names it. A sketch of nothing but edges is not that: its
    edges are drawn as lines (see '_to_glb').
    """
    if isinstance(value, list):
        return [_convert(item, tolerance, angular_tolerance, errors, shapes, geometry, failed) for item in value]
    if not isinstance(value, dict):
        return value

    converted = {
        key: _convert(item, tolerance, angular_tolerance, errors, shapes, geometry, failed)
        for key, item in value.items()
        if key != ocp_serialize.KEY_BREP
    }

    brep = value.get(ocp_serialize.KEY_BREP)
    if brep:
        try:
            digest, shape = _shape(brep, shapes)
            if digest not in geometry and digest not in failed:
                geometry[digest] = ocp_serialize.encode_gltf(_to_glb(shape, tolerance, angular_tolerance))
            if digest in geometry:
                converted[ocp_serialize.KEY_GLTF_REF] = digest
        except Exception as e:
            try:
                failed.add(ocp_serialize.payload_digest(brep))
            except Exception:
                pass
            errors.append("%s: %s" % (value.get("label") or value.get("name") or "a shape", e))

    return converted


def process(request):
    tree = request.get("tree")
    if not isinstance(tree, dict):
        raise Exception("No shape tree to convert into glTF")
    angular_tolerance = request.get("angularTolerance", 0.4)

    errors = []
    # Decoded shapes are kept across both passes: measuring the tree needs the same
    # geometry that tessellating it does, and decoding a BREP twice is the one cost
    # that measuring first would otherwise add.
    shapes = {}
    size = _size(tree, shapes, errors) if request.get("tolerance") is None else None
    tolerance = _budget(size, request)

    geometry = {}
    converted = _convert(tree, tolerance, angular_tolerance, errors, shapes, geometry, set())
    converted[ocp_serialize.KEY_GEOMETRY] = geometry
    return {
        "success": True,
        "exception": None,
        "tree": converted,
        "errors": errors,
        # What was chosen and what it was chosen from, so that the core can say so
        # rather than leave the one number that decides the size of all this unsaid.
        "tolerance": tolerance,
        "angularTolerance": angular_tolerance,
        "size": size,
    }


if __name__ == "__main__":
    # The tree arrives undecoded, as the dicts it travelled in: decoding would
    # rebuild it as one compound with the names, the placements and everything
    # else dropped (see 'ocp_serialize.decode_shape'), which is the one thing
    # this must not do - the tree *is* the answer.
    #
    # The path argv[1] carries is unused: the glTF comes back over the pipe
    # rather than as a file. handle_input() requires the argument all the same,
    # so the caller passes the operation name there.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        model = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "tree": None, "errors": []}
    wrapper_common.handle_output(model)
