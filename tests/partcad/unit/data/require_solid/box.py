#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A box: a solid, whatever its type declares."""

if __name__ == "__partcad_part__":
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    output = {"shape": BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()}
