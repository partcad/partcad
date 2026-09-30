#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to sweep a sketch profile along a path, so the core process never has to touch
# a live OCP object. The source sketch arrives as a BREP envelope, the path
# points and options arrive as plain data, and the swept solid goes back as a
# BREP envelope.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(request):
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt
    from OCP.Geom import Geom_BezierCurve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

    faces = request["sketch"]
    axis = request["axis"]
    ratio = request.get("ratio")
    accumulate = request.get("accumulate", False)

    # Decide how many points to create
    num_points = len(axis) + 1 if ratio is None else len(axis) * 3 - 1
    points = TColgp_Array1OfPnt(1, num_points)
    points.SetValue(1, gp_Pnt(0, 0, 0))

    xAcc, yAcc, zAcc = 0.0, 0.0, 0.0
    for i, point in enumerate(axis, 1):
        x, y, z = point

        if ratio is not None:
            if i != 1:
                points.SetValue(
                    3 * i - 2,
                    gp_Pnt(xAcc + x * (1 - ratio), yAcc + y * (1 - ratio), zAcc + z * (1 - ratio)),
                )
            if i != len(axis):
                points.SetValue(
                    3 * i - 1,
                    gp_Pnt(xAcc + x * ratio, yAcc + y * ratio, zAcc + z * ratio),
                )
                points.SetValue(3 * i, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))
            else:
                points.SetValue(3 * i - 1, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))
        else:
            points.SetValue(i + 1, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))

        if accumulate:
            xAcc += x
            yAcc += y
            zAcc += z

    # A Bezier curve through the points is the sweep path.
    curve = Geom_BezierCurve(points)
    edge = BRepBuilderAPI_MakeEdge(curve).Edge()
    axis_approx = BRepBuilderAPI_MakeWire(edge).Wire()

    builder = TopoDS_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)

    exp = TopExp_Explorer(faces, TopAbs_FACE)
    while exp.More():
        face = exp.Current()
        maker = BRepOffsetAPI_MakePipe(axis_approx, face)
        maker.Build()
        builder.Add(compound, maker.Shape())
        exp.Next()

    return compound


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
        model = {"success": True, "exception": None, "shape": shape}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    wrapper_common.handle_output(model)
