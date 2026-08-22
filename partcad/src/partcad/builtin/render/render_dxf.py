#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in DXF renderer (see '//builtin/render' in partcad.yaml).

DXF is the SVG projection, converted: 'render_svg.py' does the projection and
this turns its paths into DXF entities.
"""

import os
import sys
import tempfile

import svgpathtools
import ezdxf
from ezdxf.math import Vec2

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import render_svg

# How many straight segments a curve is approximated with. DXF R2010 has no
# general Bezier entity, so curves are flattened.
CURVE_SEGMENTS = 20


def convert_svg_to_dxf(svg_file, dxf_file):
    paths, _attributes, _svg_attributes = svgpathtools.svg2paths2(svg_file)

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()

    for path in paths:
        for segment in path:
            if segment.__class__.__name__ == "Line":
                msp.add_line(
                    Vec2(segment.start.real, segment.start.imag),
                    Vec2(segment.end.real, segment.end.imag),
                )
            elif segment.__class__.__name__ in ["CubicBezier", "QuadraticBezier", "Arc"]:
                for i in range(CURVE_SEGMENTS):
                    p0 = segment.point(i / float(CURVE_SEGMENTS))
                    p1 = segment.point((i + 1) / float(CURVE_SEGMENTS))
                    msp.add_line(Vec2(p0.real, p0.imag), Vec2(p1.real, p1.imag))

    doc.saveas(dxf_file)


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

        if not os.path.exists(svg_path):
            return {
                "success": False,
                "exception": f"SVG file was not created: {svg_path}",
            }

        convert_svg_to_dxf(svg_path, path)

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
