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

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import cmf_capture
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: a 3MF of several objects is all of them, not the
# first, and each object's colour is carried in the part's CMF section.
CACHE_VERSION = 2


def _plain_mesh(path):
    """The shape of every object Mesher reads at 'path', with nothing said of what they are in."""
    import ocp_serialize

    meshed = b3d.Mesher().read(path)
    if len(meshed) == 1:
        return meshed[0].wrapped
    return ocp_serialize.compound_of([mesh.wrapped for mesh in meshed])


def process(path, request):
    section = None
    try:
        try:
            shape, section = cmf_capture.read_mesh(path, request.get("cmfConvention", "3mf"))
        except Exception:
            if not request.get("fallback_import_stl", False):
                raise
            if os.path.splitext(path)[1].lower() == ".3mf":
                # Only an STL can be read the other way: a 3MF is read again as
                # Mesher reads it, without its colours, or fails as Mesher does.
                shape = _plain_mesh(path)
            else:
                # First, make sure it's not the known problem in Mesher
                shape = b3d.import_stl(path).wrapped

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
        }

    return {
        "success": True,
        "exception": None,
        # Validated and moved here, while it is live (see wrapper_common.finished).
        "shape": wrapper_common.finished(shape, cmf=section),
    }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
