#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-06
#
# Licensed under Apache License, Version 2.0.

# Some pieces of code in this file are taken from the CadQuery project:
#   https://github.com/CadQuery/cadquery
#
#   This library is free software; you can redistribute it and/or
#   modify it under the terms of the Apache Public License, v 2.0

# Some pieces of code in this file are taken from the ocp-tessellate project:
#   https://github.com/bernhard-42/ocp-tessellate/
#
#   Copyright 2023 Bernhard Walter
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#

from typing import Tuple, List


def extent_or_size(obj):
    if hasattr(obj, "Extent"):
        return obj.Extent()
    elif hasattr(obj, "Size"):
        return obj.Size()
    else:
        raise ValueError(f"Unknown type {type(obj)}")


def get_faces(shape):
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.TopExp import TopExp

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)

    for i in range(1, extent_or_size(face_map) + 1):
        yield TopoDS.Face_s(face_map.FindKey(i))


def tessellate(
    shape, tolerance: float = 0.1, angularTolerance: float = 0.1
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    from OCP.TopAbs import TopAbs_Orientation
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools

    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    if tolerance is None:
        tolerance = 0.1
    if angularTolerance is None:
        angularTolerance = 0.1

    if not BRepTools.Triangulation_s(shape, tolerance):
        BRepMesh_IncrementalMesh(
            shape,
            theLinDeflection=tolerance,
            isRelative=False,
            theAngDeflection=angularTolerance,
            isInParallel=True,
        )
    vertices: List[Tuple[float, float, float]] = []
    triangles: List[Tuple[int, int, int]] = []
    offset = 0

    for f in get_faces(shape):
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(f, loc)
        if poly is None:
            continue
        Trsf = loc.Transformation()
        reverse = f.Orientation() == TopAbs_Orientation.TopAbs_REVERSED

        # add vertices
        vertices += [
            (v.X(), v.Y(), v.Z()) for v in (poly.Node(i).Transformed(Trsf) for i in range(1, poly.NbNodes() + 1))
        ]

        # add triangles
        triangles += [
            (
                (
                    t.Value(1) + offset - 1,
                    t.Value(3) + offset - 1,
                    t.Value(2) + offset - 1,
                )
                if reverse
                else (
                    t.Value(1) + offset - 1,
                    t.Value(2) + offset - 1,
                    t.Value(3) + offset - 1,
                )
            )
            for t in poly.Triangles()
        ]

        offset += poly.NbNodes()

    return vertices, triangles
