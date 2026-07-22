#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-07-20
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to use build123d to import mesh files (3MF, STL)

import os
import sys

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        try:
            shape = b3d.Mesher().read(path)[0].wrapped
        except Exception:
            if not request.get("fallback_import_stl", False):
                raise
            # First, make sure it's not the known problem in Mesher
            shape = b3d.import_stl(path).wrapped

        return {
            "success": True,
            "exception": None,
            "shape": shape,
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
        }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
