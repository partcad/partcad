#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to measure geometry, so the core process never has to touch a live OCP object
# to do it. The shape arrives in the request as BREP (see ocp_serialize), already
# placed at whatever location the envelope carried, and only numbers go back.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize  # noqa: F401,E402
import wrapper_common  # noqa: E402


def _bbox(shape):
    """The axis-aligned bounding box of 'shape' as [xmin, ymin, zmin, xmax, ymax, zmax].

    The shape arrives already placed by the envelope's location, so the box is
    in whatever frame the caller asked for. 'None' is returned for an empty
    shape, which has no box to speak of.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return None
    # Bnd_Box.Get() reports the box grown by its gap; drop the gap so that the
    # numbers are the shape's own extent.
    box.SetGap(0.0)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return [xmin, ymin, zmin, xmax, ymax, zmax]


def process(request):
    operation = request.get("operation")
    if operation == "bbox":
        return _bbox(request["shape"])
    raise ValueError("Unknown measure operation: %r" % (operation,))


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings and
    # logs; the authoritative copy travels in the request.
    _, request = wrapper_common.handle_input()
    try:
        result = process(request)
        model = {"success": True, "exception": None, "result": result}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "result": None}
    wrapper_common.handle_output(model)
