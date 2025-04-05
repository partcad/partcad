#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to convert 3D shape projections to DXF

import os
import sys
import tempfile

import svgpathtools
import ezdxf
from ezdxf.math import Vec2

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import wrapper_render_svg


def convert_svg_to_dxf(svg_file, dxf_file):
    paths, attributes, svg_attributes = svgpathtools.svg2paths2(svg_file)

    doc = ezdxf.new(dxfversion='R2010')
    msp = doc.modelspace()

    for path in paths:
        for segment in path:
            if segment.__class__.__name__ == 'Line':
                msp.add_line(Vec2(segment.start.real, segment.start.imag),
                             Vec2(segment.end.real, segment.end.imag))
            elif segment.__class__.__name__ in ['CubicBezier', 'QuadraticBezier', 'Arc']:
                for i in range(20):
                    t0 = i / 20.0
                    t1 = (i + 1) / 20.0
                    p0 = segment.point(t0)
                    p1 = segment.point(t1)
                    msp.add_line(Vec2(p0.real, p0.imag), Vec2(p1.real, p1.imag))

    doc.saveas(dxf_file)


def process(path, request):
    try:
        svg_path = tempfile.mktemp(".svg")
        result_svg = wrapper_render_svg.process(svg_path, request)

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

# Perform conversion
response = process(path, request)

wrapper_common.handle_output(response)
