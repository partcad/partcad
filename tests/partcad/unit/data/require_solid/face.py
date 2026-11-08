#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One face of a box, and nothing else: a part with no solid in it."""

if __name__ == "__partcad_part__":
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    output = {"shape": TopExp_Explorer(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape(), TopAbs_FACE).Current()}
