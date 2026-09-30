#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to measure geometry the core did not build, so the core process never has to
# touch a live OCP object to do it. The shape arrives in the request as BREP (see
# ocp_serialize), already placed at whatever location the envelope carried, and
# only numbers go back.
#
# A shape's own size does NOT come through here: it is measured as the shape is
# encoded, in the process that built it, and travels in the envelope's metadata
# (see 'ocp_serialize.encode_shape'). What is left for this wrapper is the one
# question that cannot be answered then - how large a shape is in *another*
# object's frame, which is what 'measure.bbox(frame=...)' asks for a port.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize  # noqa: F401,E402
import shape_measure  # noqa: E402
import wrapper_common  # noqa: E402

# One implementation of each, in the module the *encoder* also calls, so that a
# size measured here and a size measured as a shape was built cannot disagree.
# Re-exported under the names this module has always used: they are what the
# unit tests exercise, and what 'process()' below dispatches to.
_bbox = shape_measure.bbox
_volumes = shape_measure.volumes
_measurements = shape_measure.measurements


def process(request):
    operation = request.get("operation")
    if operation == "bbox":
        return _bbox(request["shape"])
    if operation == "measurements":
        return _measurements(request["shape"])
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
