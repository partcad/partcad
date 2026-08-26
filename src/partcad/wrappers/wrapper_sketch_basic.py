#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to build a "basic" sketch (a face made of circle/square/rectangle outlines)
# with OCCT, so the core process never has to touch a live OCP object. The
# shape parameters arrive as plain data and the resulting face goes back as a
# BREP envelope.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


class Circle:
    def __init__(self, config):
        self.x = self.y = self.radius = 0.0
        if isinstance(config, (float, int)):
            self.radius = config
        elif isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.radius = config.get("radius", 0.0)

    def to_wire(self):
        from OCP.gp import gp_Circ, gp_Ax2, gp_Pnt, gp_Dir
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

        c = gp_Circ(gp_Ax2(gp_Pnt(self.x, self.y, 0), gp_Dir(0.0, 0.0, 1.0)), self.radius)
        edge = BRepBuilderAPI_MakeEdge(c)
        if edge.IsDone():
            return BRepBuilderAPI_MakeWire(edge.Edge()).Wire()
        return None


class Square:
    def __init__(self, config):
        self.x = self.y = self.side = 0.0
        if isinstance(config, (float, int)):
            self.side = config
        elif isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.side = config.get("side", 0.0)

    def to_wire(self):
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

        h = self.side / 2.0
        polygon = BRepBuilderAPI_MakePolygon(
            gp_Pnt(self.x + h, self.y + h, 0.0),
            gp_Pnt(self.x + h, self.y - h, 0.0),
            gp_Pnt(self.x - h, self.y - h, 0.0),
            gp_Pnt(self.x - h, self.y + h, 0.0),
            True,
        )
        return polygon.Wire() if polygon.IsDone() else None


class Rect:
    def __init__(self, config):
        self.x = self.y = self.side_x = self.side_y = 0.0
        if isinstance(config, dict):
            self.x = config.get("x", 0.0)
            self.y = config.get("y", 0.0)
            self.side_x = config.get("side-x", 0.0)
            self.side_y = config.get("side-y", 0.0)

    def to_wire(self):
        from OCP.gp import gp_Pnt
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

        hx, hy = self.side_x / 2.0, self.side_y / 2.0
        polygon = BRepBuilderAPI_MakePolygon(
            gp_Pnt(self.x + hx, self.y + hy, 0.0),
            gp_Pnt(self.x + hx, self.y - hy, 0.0),
            gp_Pnt(self.x - hx, self.y - hy, 0.0),
            gp_Pnt(self.x - hx, self.y + hy, 0.0),
            True,
        )
        return polygon.Wire() if polygon.IsDone() else None


def _outer_wire(config):
    if "circle" in config:
        return Circle(config["circle"]).to_wire()
    if "square" in config:
        return Square(config["square"]).to_wire()
    if "rectangle" in config:
        return Rect(config["rectangle"]).to_wire()
    return None


def _inner_wires(config):
    inner = config.get("inner", {})
    shapes = []
    if "circle" in inner:
        shapes.append(Circle(inner["circle"]))
    shapes.extend(Circle(c) for c in inner.get("circles", []))
    if "square" in inner:
        shapes.append(Square(inner["square"]))
    shapes.extend(Square(s) for s in inner.get("squares", []))
    if "rectangle" in inner:
        shapes.append(Rect(inner["rectangle"]))
    shapes.extend(Rect(r) for r in inner.get("rectangles", []))
    wires = [s.to_wire() for s in shapes]
    return [w for w in wires if w is not None]


def process(request):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Face

    config = request["config"]
    outer_wire = _outer_wire(config)
    if outer_wire is None:
        # BRepBuilderAPI_MakeFace(None, ...) fails deep inside pybind11 with an
        # opaque overload error; name the actual problem instead.
        raise ValueError("Cannot build a sketch face: the config names no supported outer shape")

    face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
    for inner_wire in _inner_wires(config):
        face_builder.Add(inner_wire)
    face_builder.Build()
    if not face_builder.IsDone():
        raise ValueError("Cannot build face(s): %s" % face_builder.Error())

    face_fixer = ShapeFix_Face(face_builder.Face())
    face_fixer.FixOrientation()
    face_fixer.Perform()
    return face_fixer.Result()


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
        model = {"success": True, "exception": None, "shape": shape}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    wrapper_common.handle_output(model)
