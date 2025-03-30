# This script is executed within the python sandbox environment (python runtime)
# to read OBJ files.

import os
import sys

from OCP.TopoDS import TopoDS_Compound, TopoDS_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.gp import gp_Pnt

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common

def process(path, request):
    try:
        vertices = []
        faces = []

        # Read the OBJ file
        with open(path, 'r') as file:
            for line in file:
                if line.startswith('#'):
                    continue
                if line.startswith('v '):
                    parts = line.strip().split()
                    vertex = tuple(map(float, parts[1:]))
                    vertices.append(vertex)
                elif line.startswith('f '):
                    parts = line.strip().split()
                    face = [int(part.split('/')[0]) for part in parts[1:]]
                    faces.append(face)

        # Create a compound shape to store faces
        compound = TopoDS_Compound()
        builder = TopoDS_Builder()
        builder.MakeCompound(compound)

        for face in faces:
            polygon = BRepBuilderAPI_MakePolygon()
            for vertex_idx in face:
                x, y, z = vertices[vertex_idx - 1]
                polygon.Add(gp_Pnt(x, y, z))
            polygon.Close()

            face_shape = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
            builder.Add(compound, face_shape)

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
        }

    return {
        "success": True,
        "exception": None,
        "shape": compound,
    }

path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
