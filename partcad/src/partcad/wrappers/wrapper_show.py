#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to tessellate the shapes a 'show()' is about to display.
#
# The viewer on the other end of the IDE socket is a browser: it cannot read
# BREP and has no CAD kernel to tessellate one with. So the shapes arrive here
# as the BREP envelopes the core carries (see ocp_serialize), and leave as
# binary glTF (GLB) buffers, compressed and base64-encoded by
# 'ocp_serialize.encode_gltf'. That replaces what used to happen instead:
# decoding the envelopes into live OCP objects *in the core process* and handing
# them to 'ocp_vscode', which forced a full CAD stack into the core and into
# whatever interpreter the IDE was driving.

import os
import sys
import tempfile

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common


def _shapes_of(component, shapes):
    """Collect the live shapes a component tree holds, in order.

    The BREP envelopes the core sent are already live geometry by the time they
    get here: 'wrapper_common.handle_input()' deserializes through
    'ocp_serialize', whose decode() rebuilds a TopoDS_Shape (and applies any
    placement the envelope carried). So a component is either a shape or a list
    of them - the ports list 'Shape.get_components()' appends, or an interface's
    per-port sketch components. Anything else - a null a factory produced, a
    non-shape OCCT object the codec dropped - is skipped, matching the tolerance
    of the in-process loop this replaces.
    """
    import OCP.TopoDS  # noqa: F401

    if isinstance(component, (list, tuple)):
        for item in component:
            _shapes_of(item, shapes)
        return shapes

    if isinstance(component, OCP.TopoDS.TopoDS_Shape) and not component.IsNull():
        shapes.append(component)
    return shapes


def _to_glb(shapes, tolerance, angular_tolerance):
    """Tessellate 'shapes' into one binary glTF buffer."""
    import build123d as b3d

    # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract, so
    # it silently returns None and export_gltf then fails on None.location. The
    # same reasoning as in wrapper_render_gltf.
    obj = b3d.Compound.cast(ocp_serialize.compound_of(shapes))

    # export_gltf only writes to a path, so the buffer has to come back off the
    # disk. A temp file rather than the shape's render output: a show is not a
    # render, and must not leave artifacts in the package directory.
    handle, path = tempfile.mkstemp(suffix=".glb", prefix="partcad-show-")
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
            raise Exception("Failed to tessellate the shape into glTF")
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def process(request):
    components = request.get("components") or []
    # Decoding drops the envelopes' metadata (it yields bare geometry), so the
    # core sends the names and labels alongside, one entry per component.
    names = request.get("names") or []
    labels = request.get("labels") or []
    tolerance = request.get("tolerance", 0.1)
    angular_tolerance = request.get("angularTolerance", 0.1)

    objects = []
    for index, component in enumerate(components):
        shapes = _shapes_of(component, [])
        if not shapes:
            # A component that carries no geometry (an empty ports list, say) is
            # not an error - it just has nothing to display.
            continue

        # One glTF per top-level component, so the viewer can name them
        # separately. Nested components are compounded into their parent's
        # buffer, which is what they already are visually.
        name = names[index] if index < len(names) else None
        objects.append(
            {
                "name": name or request.get("name") or ("object-%d" % index),
                "label": labels[index] if index < len(labels) else None,
                "gltf": ocp_serialize.encode_gltf(_to_glb(shapes, tolerance, angular_tolerance)),
            }
        )

    return {"success": True, "exception": None, "objects": objects}


if __name__ == "__main__":
    # The path argv[1] carries is unused: a show returns its glTF over the pipe
    # rather than writing a file. handle_input() requires the argument all the
    # same, so the caller passes the operation name there.
    _, request = wrapper_common.handle_input()
    try:
        model = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "objects": []}
    wrapper_common.handle_output(model)
