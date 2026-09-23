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
import math
import os
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


def _to_glb(shape, tolerance, angular_tolerance):
    """Tessellate one shape into a binary glTF buffer, at an absolute deflection."""
    _mesh(shape, tolerance, angular_tolerance)
    return _export(shape, angular_tolerance)


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
    than once per node that names it. A sketch of nothing but edges is the ordinary
    case of that: glTF carries triangles, and there are none.
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
