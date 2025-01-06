#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-04
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory import PartFactory
from .sketch import Sketch
from . import logging as pc_logging
from .utils import resolve_resource_path


class PartFactorySweep(PartFactory):
    depth: float
    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str
    sketch: Sketch

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSweep", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )

            if "axis" in config:
                self.axis = config["axis"]
                self.accumulate = True
            else:
                self.axis = config["axisCoords"]
                self.accumulate = False

            self.ratio = config.get("ratio", None)

            self.source_sketch_name = config.get("sketch", "sketch")
            if "project" in config:
                self.source_project_name = config["project"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_sketch_name:
                    self.source_project_name, self.source_sketch_name = resolve_resource_path(
                        source_project.name,
                        self.source_sketch_name,
                    )
                else:
                    self.source_project_name = source_project.name
            self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name

            self._create(config)

    async def instantiate(self, part):
        with pc_logging.Action("Sweep", part.project_name, part.name):
            shape = None
            try:
                self.sketch = self.project.ctx.get_sketch(self.source_sketch_spec)

                # Convert path points to TColgp_Array1OfPnt
                from OCP.TColgp import TColgp_Array1OfPnt
                from OCP.gp import gp_Pnt

                # Decide how many points to create
                num_points = len(self.axis) + 1 if self.ratio is None else len(self.axis) * 3 - 1

                # Create the array of points
                points = TColgp_Array1OfPnt(1, num_points)

                # Set first point
                points.SetValue(1, gp_Pnt(0, 0, 0))

                # Create the rest of the points
                xAcc, yAcc, zAcc = 0.0, 0.0, 0.0
                for i, point in enumerate(self.axis, 1):
                    x, y, z = point

                    if self.ratio is not None:
                        if i != 1:
                            points.SetValue(
                                3 * i - 2,
                                gp_Pnt(
                                    xAcc + x * (1 - self.ratio),
                                    yAcc + y * (1 - self.ratio),
                                    zAcc + z * (1 - self.ratio),
                                ),
                            )
                        if i != len(self.axis):
                            points.SetValue(
                                3 * i - 1,
                                gp_Pnt(
                                    xAcc + x * self.ratio,
                                    yAcc + y * self.ratio,
                                    zAcc + z * self.ratio,
                                ),
                            )
                            points.SetValue(3 * i, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))
                        else:
                            points.SetValue(3 * i - 1, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))
                    else:
                        points.SetValue(i + 1, gp_Pnt(xAcc + x, yAcc + y, zAcc + z))

                    if self.accumulate:
                        xAcc += x
                        yAcc += y
                        zAcc += z

                # Create a Bezier curve through the points
                from OCP.Geom import Geom_BezierCurve
                from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

                curve = Geom_BezierCurve(points)
                edge_maker = BRepBuilderAPI_MakeEdge(curve)
                edge = edge_maker.Edge()
                wire_maker = BRepBuilderAPI_MakeWire(edge)
                self.axis_approx = wire_maker.Wire()

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
                # TODO(clairbee): Drop the Bezier curve and use the `axis_wire` constructed above, but
                #                 replace the cut corners with elliptic arcs that connect the edges smoothly

                faces = await self.sketch.get_shape()

                from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
                from OCP.TopExp import TopExp_Explorer
                from OCP.TopAbs import TopAbs_FACE
                from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

                builder = TopoDS_Builder()
                compound = TopoDS_Compound()
                builder.MakeCompound(compound)

                exp = TopExp_Explorer(faces, TopAbs_FACE)
                while exp.More():
                    face = exp.Current()
                    maker = BRepOffsetAPI_MakePipe(self.axis_approx, face)
                    maker.Build()
                    shape = maker.Shape()
                    builder.Add(compound, shape)
                    exp.Next()

                shape = compound

            except Exception as e:
                pc_logging.exception(f"Failed to create a swept part: {e}")

            self.ctx.stats_parts_instantiated += 1

            return shape
