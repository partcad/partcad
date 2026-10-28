#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in JPEG renderer (see '//builtin/render' in partcad.yaml).

The same rasterization as PNG (see 'render_raster.py'); what is JPEG's own is
the encoder options, and the background the transparent projection has to be
flattened onto because JPEG has no alpha channel.
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import render_raster

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 2

# This projection's, for the reason 'render_svg.TESSELLATION' gives: it is drawn
# by 'render_svg.process()'. A literal, because it is read without running this.
TESSELLATION = ("projection", "reproducible", "normalize_mesh", "with_ports", "with_interfaces", "ports", "annotations")

# The request fields that are the JPEG encoder's own options. renderPM forwards
# 'configPIL' to 'PIL.Image.save()', so these reach Pillow verbatim.
ENCODER_OPTIONS = ("quality", "progressive", "optimize", "subsampling")


def process(path, request):
    # Only the options the request carries are passed on, so that Pillow's own
    # defaults remain the defaults for everything else.
    config_pil = {option: request[option] for option in ENCODER_OPTIONS if request.get(option) is not None}
    return render_raster.process(path, request, "JPEG", config_pil=config_pil)
