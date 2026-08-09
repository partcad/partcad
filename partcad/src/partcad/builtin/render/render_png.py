#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in PNG renderer (see '//builtin/render' in partcad.yaml).

PNG is the SVG projection, rasterized: 'render_svg.py' does the projection and
this scales the result to the requested pixel size.
"""

import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import render_svg

import svglib.svglib as svglib
import reportlab.graphics.renderPM as renderPM


def process(path, request):
    try:
        svg_path = tempfile.mktemp(".svg")
        result_svg = render_svg.process(svg_path, request)
        if not result_svg.get("success", False):
            return {
                "success": False,
                "exception": f"SVG render failed: {result_svg.get('exception')}",
            }

        # Render the raster image
        drawing = svglib.svg2rlg(svg_path)
        if drawing is None:
            return {
                "success": False,
                "exception": "Failed to convert to RLG. Aborting.",
            }

        scale_width = float(request.get("width", 512)) / float(drawing.width)
        scale_height = float(request.get("height", 512)) / float(drawing.height)
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

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
