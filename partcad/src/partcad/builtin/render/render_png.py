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

DEFAULT_SIZE = 512


def _scale(drawing, request):
    """How much to scale the projection by to fit the requested pixel size.

    Both dimensions bound the result, so the smaller ratio wins. Only one of
    them needs to be given: the other is then whatever keeps the aspect ratio,
    rather than the default silently bounding the dimension that was asked for.
    """
    width = request.get("width")
    height = request.get("height")
    if width is None and height is None:
        width = height = DEFAULT_SIZE

    ratios = []
    if width is not None:
        ratios.append(float(width) / float(drawing.width))
    if height is not None:
        ratios.append(float(height) / float(drawing.height))
    return min(ratios)


def process(path, request):
    svg_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            svg_path = f.name
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

        scale = _scale(drawing, request)
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
    finally:
        # Every path above leaves through here, so the intermediate SVG never
        # accumulates in the temporary directory of a long render job.
        if svg_path and os.path.exists(svg_path):
            try:
                os.remove(svg_path)
            except OSError:
                pass
