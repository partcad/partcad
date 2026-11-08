#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to find where each material of an object is - its clusters, as the "Materials"
# callout of the IDE's 3D view writes them (see 'material_clusters', which the SVG
# renderer calls for the same callout on a picture). The tree arrives as BREP and
# only data goes back: names, points and the paths of nodes.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import material_clusters  # noqa: E402
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1


def process(request):
    operation = request.get("operation")
    if operation != "clusters":
        raise ValueError("Unknown materials operation: %r" % (operation,))
    # Decoded here rather than by 'handle_input': the clusters name the nodes of
    # the tree by where they are in it, and decoding it whole would rebuild it as
    # one compound with the nodes gone.
    _whole, tree = ocp_serialize.decode_tree(request["shape"])
    return material_clusters.clusters(tree, request.get("distance", 0))


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings and
    # logs; the authoritative copy travels in the request.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        result = process(request)
        model = {"success": True, "exception": None, "result": result}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "result": None}
    wrapper_common.handle_output(model)
