#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to use build123d

import os
import sys

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

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        shape_list = b3d.import_svg(
            request["path"],
            flip_y=request["flip_y"],
            ignore_visibility=request["ignore_visibility"],
        )

        use_wires = request["use_wires"]
        use_faces = request["use_faces"]

        faces = []
        if use_wires or not use_faces:
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

        if use_faces or not use_wires:
            # Unwrap the build123d faces: only raw OCP shapes may cross the pipe
            faces.extend([imported_face.wrapped for imported_face in shape_list.faces()])

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

        return {
            "success": True,
            "exception": None,
            "shape": shape,
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": wrapper_common.exception_to_str(e),
        }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
