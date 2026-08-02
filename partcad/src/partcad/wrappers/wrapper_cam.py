#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to run the manufacturability shape analysis the 'pc test' CAM checks need, so
# the core process never has to touch a live OCP object. The shape arrives as a
# BREP envelope and the analysis result goes back as plain data.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(request):
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties

    shape = request["shape"]
    fbp = ShapeAnalysis_FreeBoundsProperties(shape)
    fbp.Perform()
    return fbp.NbFreeBounds()


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        free_bounds = process(request)
        model = {"success": True, "exception": None, "free_bounds": free_bounds}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "free_bounds": None}
    wrapper_common.handle_output(model)
