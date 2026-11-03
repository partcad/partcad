#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 3MF exporter (see '//builtin/export' in partcad.yaml).

The geometry is CadQuery's 3MF writer's, one mesh object of the whole shape. A
shape that states CMF is then given it as the 3MF core specification states
appearance: a base material per CMF set, with its name and its sRGB display
colour, which the object and each of its triangles name (see 'cmf_3mf'). What
PartCAD reads a 3MF with reads it back ('cmf_capture.read_mesh'), and so does
every reader built on lib3mf, now that the package types its relationships the
way lib3mf requires (see 'cmf_3mf.finish').
"""

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

import cadquery as cq

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: base materials per CMF set, and the package's
# parts typed so that lib3mf reads it.
CACHE_VERSION = 2

# How this implementation meshes what it is handed, so that the files of one
# object written together can share one decoding of it and one mesh (see
# 'wrapper_export.TESSELLATION_NAME'): relative, through cadquery's
# 'Shape.tessellate()', which meshes as the STL exporter does. Only the mesh is
# left on the shape, and what is written is decided by the geometry and that
# mesh alone. (It runs in CadQuery's layer and the STL exporter in the base, so
# the two are not written by one process; a file type of the same layer that
# meshes the same way would share with it.)
TESSELLATION = ("relative", "tolerance", "angularTolerance")


def process(path, request):
    try:
        obj = request["wrapped"]

        cq_solid = cq.Solid.makeBox(1, 1, 1)
        cq_solid.wrapped = obj

        cq.exporters.export(
            cq_solid,
            path,
            tolerance=request.get("tolerance", 0.1),
            angularTolerance=request.get("angularTolerance", 0.1),
        )

        # The faces are meshed now, by the writer, as it wrote them: which set
        # each triangle is in is counted off that very mesh.
        import cmf_3mf

        warnings = []
        per_triangle = cmf_3mf.triangle_sets(obj, request.get("shape_tree"), warnings)
        if not cmf_3mf.finish(path, per_triangle) and per_triangle is not None:
            warnings.append(
                "The colours of %s are not in its 3MF: the file's triangles are not the ones they were counted on"
                % (request.get("shape_name") or "the shape")
            )

        return {"success": True, "exception": None, "files": [], "warnings": warnings}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
