#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering

import os
import sys

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common


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


def process(path, request):
    try:
        wrapped = request["wrapped"]
        if request.get("normalize_mesh"):
            wrapped = _normalize_mesh(wrapped)

        b3d_obj = b3d.Solid.make_box(1, 1, 1)
        b3d_obj.wrapped = wrapped

        viewport_origin = tuple(request.get("viewport_origin"))
        viewport_up = tuple(request.get("viewport_up", [0, 0, 1]))
        visible, hidden = b3d_obj.project_to_viewport(
            viewport_origin=viewport_origin,
            viewport_up=viewport_up,
        )
        # visible = b3d_obj.project_to_viewport(
        #     viewport_origin=viewport_origin,
        #     ignore_hidden=True,
        # )[0]
        max_dimension = max(
            # *b3d.Compound(children=visible + hidden)
            *b3d.Compound(children=visible)
            .bounding_box()
            .size
        )
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
            line_weight=request["line_weight"],
        )
        # exporter.add_layer(
        #     "Hidden",
        #     line_color=(32, 64, 32),
        #     line_type=b3d.LineType.ISO_DOT,
        # )
        try:
            exporter.add_shape(visible, layer="Visible")
            # exporter.add_shape(hidden, layer="Hidden")
        except:
            pass
        exporter.write(path)

        return {
            "success": True,
            "exception": None,
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e.with_traceback(None)),
        }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()

    # Perform rendering
    response = process(path, request)

    wrapper_common.handle_output(response)
