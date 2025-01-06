#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from OCP.gp import (
    gp_Circ,
    gp_Ax2,
    gp_Pnt,
    gp_Dir,
)
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
)
from OCP.ShapeFix import (
    ShapeFix_Face,
)

from .sketch_factory import SketchFactory
from . import logging as pc_logging


class Circle:
    x: float = 0.0
    y: float = 0.0
    radius: float = 0.0

    def __init__(self, config: object = {}):
        if isinstance(config, float) or isinstance(config, int):
            self.radius = config
        if isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.radius = config.get("radius", 0.0)

    def to_wire(self):
        c = gp_Circ(
            gp_Ax2(
                gp_Pnt(self.x, self.y, 0),
                gp_Dir(0.0, 0.0, 1.0),
            ),
            self.radius,
        )
        edge = BRepBuilderAPI_MakeEdge(c)
        if edge.IsDone():
            return BRepBuilderAPI_MakeWire(edge.Edge()).Wire()
        return None


class Square:
    x: float = 0.0
    y: float = 0.0
    side: float = 0.0

    def __init__(self, config: object = {}):
        if isinstance(config, float) or isinstance(config, int):
            self.side = config
        if isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.side = config.get("side", 0.0)

    def to_wire(self):
        polygon = BRepBuilderAPI_MakePolygon(
            gp_Pnt(
                self.x + self.side / 2.0,
                self.y + self.side / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x + self.side / 2.0,
                self.y - self.side / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x - self.side / 2.0,
                self.y - self.side / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x - self.side / 2.0,
                self.y + self.side / 2.0,
                0.0,
            ),
            True,
        )
        if polygon.IsDone():
            return polygon.Wire()
        return None


class Rect:
    x: float = 0.0
    y: float = 0.0
    side_x: float = 0.0
    side_y: float = 0.0

    def __init__(self, config: object = {}):
        if isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.side_x = config.get("side-x", 0.0)
            self.side_y = config.get("side-y", 0.0)

    def to_wire(self):
        polygon = BRepBuilderAPI_MakePolygon(
            gp_Pnt(
                self.x + self.side_x / 2.0,
                self.y + self.side_y / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x + self.side_x / 2.0,
                self.y - self.side_y / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x - self.side_x / 2.0,
                self.y - self.side_y / 2.0,
                0.0,
            ),
            gp_Pnt(
                self.x - self.side_x / 2.0,
                self.y + self.side_y / 2.0,
                0.0,
            ),
            True,
        )
        if polygon.IsDone():
            return polygon.Wire()
        return None


# TODO(clairbee): distinguish between inner and outer wires?
#                 see Face::_make_from_wires in build123d/topology.py
class SketchFactoryBasic(SketchFactory):
    outer_circle: Circle = None
    outer_square: Square = None
    outer_rect: Rect = None
    inner_circles: list[Circle] = []
    inner_squares: list[Square] = []
    inner_rects: list[Rect] = []

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitBasic", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )

            if "circle" in config:
                self.outer_circle = Circle(config["circle"])
            if "square" in config:
                self.outer_square = Square(config["square"])
            if "rectangle" in config:
                self.outer_rect = Rect(config["rectangle"])

            if "inner" in config:
                inner = config["inner"]
                if "circle" in inner:
                    self.inner_circles = [Circle(inner["circle"])]
                if "circles" in inner:
                    self.inner_circles.extend([Circle(c) for c in inner["circles"]])
                if "square" in inner:
                    self.inner_squares = [Square(inner["square"])]
                if "squares" in inner:
                    self.inner_squares.extend([Square(s) for s in inner["squares"]])
                if "rectangle" in inner:
                    self.inner_rects = [Rect(inner["rectangle"])]
                if "rectangles" in inner:
                    self.inner_rects.extend([Rect(r) for r in inner["rectangles"]])

            self._create(config)

    async def instantiate(self, sketch):
        with pc_logging.Action("Basic", sketch.project_name, sketch.name):
            shape = None

            try:
                # Get the outer wire
                outer_wire = None
                if not self.outer_circle is None:
                    outer_wire = self.outer_circle.to_wire()
                if not self.outer_square is None:
                    outer_wire = self.outer_square.to_wire()
                if not self.outer_rect is None:
                    outer_wire = self.outer_rect.to_wire()

                # # Fix the outer wire
                # wire_fixer = ShapeFix_Shape(outer_wire)
                # wire_fixer.Perform()
                # fixed_outer_wire_shape = wire_fixer.Shape()
                # outer_wire = TopoDS.Wire_s(fixed_outer_wire_shape)

                # Collect inner wires
                inner_wires = []
                for inner_circle in self.inner_circles:
                    inner_wire = inner_circle.to_wire()
                    if not inner_wire is None:
                        inner_wires.append(inner_wire)
                for inner_square in self.inner_squares:
                    inner_wire = inner_square.to_wire()
                    if not inner_wire is None:
                        inner_wires.append(inner_wire)
                for inner_rect in self.inner_rects:
                    inner_wire = inner_rect.to_wire()
                    if not inner_wire is None:
                        inner_wires.append(inner_wire)

                # Build the face
                face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
                for inner_wire in inner_wires:
                    face_builder.Add(inner_wire)

                face_builder.Build()
                if not face_builder.IsDone():
                    raise ValueError(f"Cannot build face(s): {face_builder.Error()}")

                face = face_builder.Face()

                # # Fix the face
                face_fixer = ShapeFix_Face(face)
                face_fixer.FixOrientation()
                face_fixer.Perform()
                shape = face_fixer.Result()
            except Exception as e:
                pc_logging.exception("Failed to create a basic sketch: %s" % e)

            self.ctx.stats_sketches_instantiated += 1

            pc_logging.debug("Basic sketch instantiated")
            return shape
