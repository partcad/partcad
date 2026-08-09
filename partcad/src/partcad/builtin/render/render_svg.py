#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in SVG renderer (see '//builtin/render' in partcad.yaml).

'render_png.py' and 'render_dxf.py' both start from what this produces, so they
import 'process()' from here rather than duplicating the projection.
"""

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def viewport_origin(request):
    """Where the shape is looked at from, when the request does not say.

    A sketch is flat, so it is looked at head-on; anything else is looked at
    from a corner, which is what makes a 3D shape read as 3D.
    """
    origin = request.get("viewport_origin")
    if origin:
        return tuple(origin)
    if request.get("shape_kind") == "sketch":
        return (0, 0, 100)
    return (100, -100, 100)


def viewport_up(request):
    """Which way is up in the projection, when the request does not say."""
    up = request.get("viewport_up")
    if up:
        return tuple(up)
    if request.get("shape_kind") == "sketch":
        return (0, 1, 0)
    return (0, 0, 1)


def _normalize_mesh(shape):
    """Round-trip a triangulation-only shape (e.g. an SDF mesh) through STL.

    Such a shape has no topological edges for 'project_to_viewport' to use;
    writing it to STL and reading it back yields a shape it can project. This
    runs inside the render runtime, so no OCCT mesh handling leaks into the main
    process, and the normalized shape never crosses a runtime boundary.
    """
    import tempfile
    from OCP.StlAPI import StlAPI_Writer, StlAPI_Reader
    from OCP.TopoDS import TopoDS_Shape

    fd, tmp_path = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    try:
        writer = StlAPI_Writer()
        if not writer.Write(shape, tmp_path):
            from OCP.BRepMesh import BRepMesh_IncrementalMesh

            BRepMesh_IncrementalMesh(shape, 0.1).Perform()
            writer.Write(shape, tmp_path)
        reader = StlAPI_Reader()
        result = TopoDS_Shape()
        if reader.Read(result, tmp_path) and not result.IsNull():
            return result
        return shape
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def needs_mesh_normalization(request):
    """SDF parts are meshes: a triangulation with no edges to project."""
    if request.get("normalize_mesh") is not None:
        return bool(request["normalize_mesh"])
    return request.get("shape_type") == "sdf"


def process(path, request):
    try:
        wrapped = request["wrapped"]
        if needs_mesh_normalization(request):
            wrapped = _normalize_mesh(wrapped)

        b3d_obj = b3d.Solid.make_box(1, 1, 1)
        b3d_obj.wrapped = wrapped

        visible, hidden = b3d_obj.project_to_viewport(
            viewport_origin=viewport_origin(request),
            viewport_up=viewport_up(request),
        )
        max_dimension = max(*b3d.Compound(children=visible).bounding_box().size)
        if max_dimension == 0:
            max_dimension = 4
        scale = 512.0 / max_dimension
        exporter = b3d.ExportSVG(
            scale=scale,
            precision=10,
        )
        exporter.add_layer(
            "Visible",
            line_color=(64, 192, 64),
            line_weight=request.get("line_weight", 1.0),
        )
        try:
            exporter.add_shape(visible, layer="Visible")
        except:
            pass
        exporter.write(path)

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
