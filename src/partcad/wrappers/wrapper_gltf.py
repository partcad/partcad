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

import os
import sys
import tempfile

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common


def _to_glb(shape, tolerance, angular_tolerance):
    """Tessellate one shape into a binary glTF buffer."""
    import build123d as b3d

    # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract, so
    # it silently returns None and export_gltf then fails on None.location. The
    # same reasoning as in wrapper_render_gltf.
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
            linear_deflection=tolerance,
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


def _convert(value, tolerance, angular_tolerance, errors):
    """'value' with every piece of BREP in it replaced by glTF.

    A walk of the whole structure rather than of the places a node's geometry is
    known to sit. Geometry turns up in more than one of them - a node's own, the
    nodes inside it, the sketches the ports of an object are drawn with - and which
    ones those are is the core's business: it adds one without telling this file,
    and a walk that knew the list would quietly hand the browser BREP the day it
    did. Anything that is not geometry is copied through untouched.

    A shape that will not tessellate loses its geometry and keeps its place, with
    the reason collected for the caller to report. A sketch of nothing but edges is
    the ordinary case of that: glTF carries triangles, and there are none.
    """
    if isinstance(value, list):
        return [_convert(item, tolerance, angular_tolerance, errors) for item in value]
    if not isinstance(value, dict):
        return value

    converted = {
        key: _convert(item, tolerance, angular_tolerance, errors)
        for key, item in value.items()
        if key != ocp_serialize.KEY_BREP
    }

    brep = value.get(ocp_serialize.KEY_BREP)
    if brep:
        try:
            shape = ocp_serialize.shape_from_payload(brep)
            converted[ocp_serialize.KEY_GLTF] = ocp_serialize.encode_gltf(_to_glb(shape, tolerance, angular_tolerance))
        except Exception as e:
            errors.append("%s: %s" % (value.get("label") or value.get("name") or "a shape", e))

    return converted


def process(request):
    tree = request.get("tree")
    if not isinstance(tree, dict):
        raise Exception("No shape tree to convert into glTF")
    tolerance = request.get("tolerance", 0.1)
    angular_tolerance = request.get("angularTolerance", 0.1)

    errors = []
    converted = _convert(tree, tolerance, angular_tolerance, errors)
    return {"success": True, "exception": None, "tree": converted, "errors": errors}


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
