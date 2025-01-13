#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering

import os
import sys

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        b3d_obj = b3d.Solid.make_box(1, 1, 1)
        b3d_obj.wrapped = request["wrapped"]

        viewport_origin = tuple(request["viewport_origin"])
        visible, hidden = b3d_obj.project_to_viewport(viewport_origin=viewport_origin)
        # visible = b3d_obj.project_to_viewport(
        #     viewport_origin=viewport_origin,
        #     ignore_hidden=True,
        # )[0]
        max_dimension = max(
            # *b3d.Compound(children=visible + hidden)
            *b3d.Compound(children=visible)
            .bounding_box()
            .size
        )
        if max_dimension == 0:
            max_dimension = 4
        scale = 512.0 / max_dimension
        exporter = b3d.ExportSVG(
            scale=scale,
            precision=10,
        )
        exporter.add_layer(
            "Visible",
            line_color=(64, 192, 64),
            line_weight=request["line_weight"],
        )
        # exporter.add_layer(
        #     "Hidden",
        #     line_color=(32, 64, 32),
        #     line_type=b3d.LineType.ISO_DOT,
        # )
        try:
            exporter.add_shape(visible, layer="Visible")
            # exporter.add_shape(hidden, layer="Hidden")
        except:
            pass
        exporter.write(path)

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
