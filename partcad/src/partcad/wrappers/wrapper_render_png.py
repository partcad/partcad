#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering and
# to reduce Python dependencies on the host environment

import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import wrapper_render_svg

import svglib.svglib as svglib
import reportlab.graphics.renderPM as renderPM


def process(path, request):
    try:
        svg_path = tempfile.mktemp(".svg")
        wrapper_render_svg.process(svg_path, request)

        # Render the raster image
        drawing = svglib.svg2rlg(svg_path)
        if drawing is None:
            return {
                "success": False,
                "exception": "Failed to convert to RLG. Aborting.",
            }

        scale_width = float(request["width"]) / float(drawing.width)
        scale_height = float(request["height"]) / float(drawing.height)
        scale = min(scale_width, scale_height)
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        renderPM.drawToFile(
            drawing,
            path,
            fmt="PNG",
            configPIL={"transparent": True},
        )

        return {
            "success": True,
            "exception": None,
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e.with_traceback(None)),
        }


path, request = wrapper_common.handle_input()

# Perform rendering
response = process(path, request)

wrapper_common.handle_output(response)
