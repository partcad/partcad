import os
import sys
import base64
import pickle

from OCP.TColgp import TColgp_Array1OfPnt
from OCP.gp import gp_Pnt
from OCP.Geom import Geom_BezierCurve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common


def process(request):
    try:
        axis = request["axis"]
        accumulate = request["accumulate"]
        ratio = request.get("ratio", None)
        sketch_shape = request["sketch_shape"]

        # Decide how many points to create
        num_points = len(axis) + 1 if ratio is None else len(axis) * 3 - 1

        # Create the array of points
        points = TColgp_Array1OfPnt(1, num_points)

        # Set first point
        points.SetValue(1, gp_Pnt(0, 0, 0))

        # Create the rest of the points
        xAcc, yAcc, zAcc = 0.0, 0.0, 0.0
        for i, point in enumerate(axis, 1):
            x, y, z = point

            if ratio is not None:
                if i != 1:
                    points.SetValue(
                        3 * i - 2,
                        gp_Pnt(
                            xAcc + x * (1 - ratio),
                            yAcc + y * (1 - ratio),
                            zAcc + z * (1 - ratio),
                        ),
                    )
                if i != len(axis):
                    points.SetValue(
                        3 * i - 1,
                        gp_Pnt(
                            xAcc + x * ratio,
                            yAcc + y * ratio,
                            zAcc + z * ratio,
                        ),
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

        # Create a Bezier curve through the points
        curve = Geom_BezierCurve(points)
        edge_maker = BRepBuilderAPI_MakeEdge(curve)
        edge = edge_maker.Edge()
        wire_maker = BRepBuilderAPI_MakeWire(edge)
        axis_wire = wire_maker.Wire()

        # # Create a wire through the points (for debugging)
        # from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        # from OCP.BRep import BRep_Tool
        # wire_maker = BRepBuilderAPI_MakeWire()
        # for i in range(1, num_points):
        #     current = i
        #     next = i + 1
        #     if self.ratio is not None:
        #         if i % 3 == 0:
        #             continue
        #         if (i + 1) % 3 == 0:
        #             next = i + 2
        #     edge_maker = BRepBuilderAPI_MakeEdge(points.Value(current), points.Value(next))
        #     edge = edge_maker.Edge()
        #     wire_maker.Add(edge)
        # self.axis_wire = wire_maker.Wire()
        # from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound
        # builder = TopoDS_Builder()
        # compound = TopoDS_Compound()
        # builder.MakeCompound(compound)
        # builder.Add(compound, self.axis_approx)
        # builder.Add(compound, self.axis_wire)
        # shape = compound

        # Note: The above code can be used for debugging the curve instead of the below code
        # TODO(clairbee): Drop the Bezier curve and use the axis_wire constructed above, but
        #                 replace the cut corners with elliptic arcs that connect the edges smoothly

        builder = TopoDS_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)

        exp = TopExp_Explorer(sketch_shape, TopAbs_FACE)
        while exp.More():
            face = exp.Current()
            maker = BRepOffsetAPI_MakePipe(axis_wire, face)
            maker.Build()
            shape = maker.Shape()
            builder.Add(compound, shape)
            exp.Next()

        return {
            "success": True,
            "exception": None,
            "shape": compound,
            "components": [compound],
        }

    except Exception as e:
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
            "components": [],
        }


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    result = process(request)
    wrapper_common.handle_output(result)
