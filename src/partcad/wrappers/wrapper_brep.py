# This script is executed within the python sandbox environment (python runtime)
# to read BREP files.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1


def process(path, request):
    try:
        # Either format, as a payload is read: a package's '.brep' is ASCII,
        # and the parts an interference check leaves behind are binary (see
        # 'ocp_serialize.shape_from_brep_file').
        shape = ocp_serialize.shape_from_brep_file(path)
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
        "shape": wrapper_common.finished(shape),
    }


path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
