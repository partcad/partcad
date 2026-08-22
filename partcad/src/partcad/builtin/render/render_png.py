#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in PNG renderer (see '//builtin/render' in partcad.yaml).

PNG is the SVG projection, rasterized. Everything it does is what JPEG does too,
so it lives in 'render_raster.py'; what is left here is the one thing that is
PNG's own -- keeping the transparent background the projection was drawn with.
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import render_raster


def process(path, request):
    return render_raster.process(path, request, "PNG", config_pil={"transparent": True})
