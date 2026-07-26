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
            "exception": wrapper_common.exception_to_str(e),
        }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
