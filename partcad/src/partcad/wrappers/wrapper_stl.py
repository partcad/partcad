import os
import sys
import base64
import pickle
import traceback

import build123d as b3d

from OCP.RWStl import RWStl
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Solid
from OCP.TopAbs import TopAbs_FACE
from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_Solid, BRepCheck_Status
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

sys.path.append(os.path.dirname(__file__))
import wrapper_common

def process(path, request):
    try:
        try:
            meshed = b3d.Mesher().read(path)
            shape = meshed[0].wrapped
        except Exception:
            builder = BRep_Builder()
            reader = RWStl.ReadFile_s(os.fsdecode(path))

            if not reader:
                raise RuntimeError("Failed to read the STL file")

            # Build and check the faces
            face = TopoDS_Face()
            builder.MakeFace(face, reader)
            if face.IsNull():
                raise RuntimeError("Failed to read the STL file: Null")
            if face.ShapeType() != TopAbs_FACE:
                raise RuntimeError("Failed to read the STL file: Wrong shape type")
            if face.Infinite():
                raise RuntimeError("Failed to read the STL file: Infinite")

            # Build and check the shell
            shell = TopoDS_Shell()
            builder.MakeShell(shell)
            builder.Add(shell, face)
            shell_check = BRepCheck_Shell(shell)
            shell_check_result = shell_check.Closed()
            if shell_check_result != BRepCheck_Status.BRepCheck_NoError:
                if shell_check_result == BRepCheck_Status.BRepCheck_NotClosed:
                    raise RuntimeError("Failed to read the STL file: Shell is not closed")
                else:
                    raise RuntimeError("Failed to read the STL file: Shell check failed")

            # Build and check the solid
            solid = TopoDS_Solid()
            builder.MakeSolid(solid)
            builder.Add(solid, shell)
            if solid.IsNull():
                raise RuntimeError("Failed to read the STL file: Null solid")
            if solid.Infinite():
                raise RuntimeError("Failed to read STL file: Infinite solid")
            solid_check = BRepCheck_Solid(solid)
            solid_check.Minimum()
            statuses = solid_check.Status()
            if statuses.Size() > 0 and statuses.First() != BRepCheck_Status.BRepCheck_NoError:
                raise RuntimeError("Failed to read the STL file: Solid check failed: %s" % statuses.First())
            gprops = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, gprops)
            if gprops.Mass() <= 0:
                raise RuntimeError("Failed to read the STL file: Zero or negative volume")

            shape = solid

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e), "shape": None}

    return {"success": True, "exception": None, "shape": shape}

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    result = process(path, request)
    wrapper_common.handle_output(result)
