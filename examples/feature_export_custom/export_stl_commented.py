#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An STL exporter this package supplies instead of the built-in one.

Declared as the 'path' of 'stl' in this package's 'export:' section, which is
all it takes for every STL this package produces to be written by this script
rather than by '//builtin/export'.

It runs inside a PartCAD sandbox, so it may import OCP. PartCAD hands it:

    request  -- the shape in 'request["wrapped"]', plus every field of the
                'stl' section ('tolerance', 'angularTolerance', 'comment'
                here), plus 'shape_name', 'shape_kind' and 'shape_type'
    path     -- the file to write

and reads back either a global 'output' or, as here, whatever
'process(path, request)' returns.

What it does differently from the built-in exporter: it always writes ASCII STL,
and it names the solid after the package's 'comment' - the closest thing the
format has to one.
"""

import os


def _rename_solid(path, comment):
    """Put 'comment' on the 'solid'/'endsolid' lines of an ASCII STL file."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if lines and lines[0].startswith("solid"):
        lines[0] = "solid %s" % comment
    if len(lines) > 1 and lines[-1].startswith("endsolid"):
        lines[-1] = "endsolid %s" % comment
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def process(path, request):
    try:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        obj = request["wrapped"]

        BRepMesh_IncrementalMesh(
            obj,
            theLinDeflection=request.get("tolerance", 0.1),
            isRelative=True,
            theAngDeflection=request.get("angularTolerance", 0.1),
            isInParallel=True,
        )

        writer = StlAPI_Writer()
        writer.ASCIIMode = True
        if not writer.Write(obj, path) or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception("Failed to create the STL file: %s" % path)

        comment = request.get("comment")
        if comment:
            _rename_solid(path, comment)

        return {"success": True, "exception": None}
    except Exception as e:
        return {"success": False, "exception": str(e)}
