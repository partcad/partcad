#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import build123d as b3d

from OCP.ShapeExtend import ShapeExtend_WireData
from OCP.ShapeFix import (
    ShapeFix_Shape,
)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BOPAlgo import BOPAlgo_Operation
from OCP.TopTools import TopTools_ListOfShape

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.TopoDS import TopoDS

from . import logging as pc_logging
from .sketch_factory_file import SketchFactoryFile
from .sentry import instrument


@instrument()
class SketchFactorySvg(SketchFactoryFile):
    flip_y = True
    ignore_visibility = False
    use_wires = False
    use_faces = False

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSVG", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".svg",
            )

            if "flip-y" in config:
                self.flip_y = bool(config["flip-y"])

            if "ignore-visibility" in config:
                self.ignore_visibility = bool(config["ignore-visibility"])

            if "use-wires" in config:
                self.use_wires = bool(config["use-wires"])

            if "use-faces" in config:
                self.use_faces = bool(config["use-faces"])

            self._create(config)

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("SVG", sketch.project_name, sketch.name):
            try:
                shape_list = b3d.import_svg(
                    self.path,
                    flip_y=self.flip_y,
                    ignore_visibility=self.ignore_visibility,
                )

                faces = []
                if self.use_wires or not self.use_faces:
                    wires = shape_list.wires()

                    wire_merger = ShapeExtend_WireData()
                    for wire in wires:
                        wire_merger.Add(wire.wrapped)
                    wire = wire_merger.Wire()

                    wire_fixer = ShapeFix_Shape(wire)
                    wire_fixer.Perform()
                    fixed_wire_shape = wire_fixer.Shape()
                    wire = TopoDS.Wire_s(fixed_wire_shape)

                    face_builder = BRepBuilderAPI_MakeFace(wire, True)
                    face_builder.Build()
                    if not face_builder.IsDone():
                        raise ValueError(f"Cannot build face(s): {face_builder.Error()}")

                    face = face_builder.Face()

                    face_fixer = ShapeFix_Shape(face)
                    face_fixer.Perform()
                    fixed_face_shape = face_fixer.Shape()
                    face = TopoDS.Face_s(fixed_face_shape)

                    faces.append(face)

                if self.use_faces or not self.use_wires:
                    faces.extend(shape_list.faces())

                if len(faces) == 1:
                    shape = faces[0]
                else:
                    # TODO(clairbee): verify this branch
                    shapes = TopTools_ListOfShape()
                    for face in faces:
                        shapes.Append(face)
                    face_fuser = BRepAlgoAPI_Fuse()
                    face_fuser.SetArguments(shapes)
                    face_fuser.SetOperation(BOPAlgo_Operation.BOPAlgo_FUSE)
                    # face_fuser.SetRunParallel(True)
                    face_fuser.Build()
                    if face_fuser.IsDone():
                        shape = face_fuser.Shape()
                    else:
                        shape = None
            except Exception as e:
                pc_logging.exception("Failed to import the SVG file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
