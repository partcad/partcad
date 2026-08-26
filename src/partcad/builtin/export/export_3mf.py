#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 3MF exporter (see '//builtin/export' in partcad.yaml)."""

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

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
