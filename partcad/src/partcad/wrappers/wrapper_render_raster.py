#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering and
# to reduce Python dependencies on the host environment

# The shared half of every raster format PartCAD renders. PNG and JPEG differ
# only in what PIL is told to write at the very last step, so both wrappers
# project the shape to SVG here, rasterize it here, and pass their own PIL
# options in.
#
# Keeping the two on one code path is also what keeps the dependency list short:
# rasterizing needs svglib, reportlab and rlPyCairo (see sandbox_versions), and
# JPEG adds nothing to that. reportlab already depends on Pillow, and renderPM
# hands the finished image to 'PIL.Image.save()' with 'configPIL' as its keyword
# arguments -- so every JPEG encoder option is reachable without a single extra
# package in the sandbox.

import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import wrapper_render_svg

import svglib.svglib as svglib
import reportlab.graphics.renderPM as renderPM

# What a raster render is drawn on top of when nothing else is asked for. The
# SVG has a transparent background and JPEG has no alpha channel at all, so
# some color has to be chosen; white matches what PNG has always produced.
DEFAULT_BACKGROUND = 0xFFFFFF


def parse_background(value):
    """Turn a background color from the render options into reportlab's integer.

    Accepts what a YAML config can hold: an integer already in 0xRRGGBB form, or
    a string such as "#ffffff", "ffffff" or "#fff".
    """
    if value is None:
        return DEFAULT_BACKGROUND
    if isinstance(value, int):
        return value

    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        # The CSS shorthand: each digit stands for a doubled byte.
        text = "".join(digit * 2 for digit in text)
    if len(text) != 6:
        raise ValueError("Invalid background color: %r" % (value,))
    return int(text, 16)


def process(path, request, fmt, config_pil=None):
    """Render the requested shape into 'path' as a raster image.

    'fmt' is the format name renderPM expects ("PNG", "JPEG"); 'config_pil' is
    passed through to 'PIL.Image.save()' by renderPM.
    """
    try:
        # A private directory, not a bare temporary name: 'tempfile.mktemp()'
        # only invents a path and reserves nothing, leaving a window in which
        # another local process can plant a symlink there and have the SVG
        # written through it. The directory also takes care of the cleanup.
        with tempfile.TemporaryDirectory(prefix="partcad-render-") as temp_dir:
            svg_path = os.path.join(temp_dir, "projection.svg")

            svg_response = wrapper_render_svg.process(svg_path, request)
            # Report why the projection failed instead of the "Failed to convert
            # to RLG" that an absent or empty SVG would produce below.
            if not svg_response.get("success", False):
                return svg_response

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
            fmt=fmt,
            bg=parse_background(request.get("background")),
            configPIL=config_pil,
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
