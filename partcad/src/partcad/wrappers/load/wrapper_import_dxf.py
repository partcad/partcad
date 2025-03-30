#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to use CadqUery

import os
import sys

import cadquery as cq

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common


def process(path, request):
    try:
        workplane = cq.importers.importDXF(
            filename=request["path"],
            tol=request["tolerance"],
            include=request["include"],
            exclude=request["exclude"],
        )
        shape = workplane.val().wrapped

        return {
            "success": True,
            "exception": None,
            "shape": shape,
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": e,
        }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
