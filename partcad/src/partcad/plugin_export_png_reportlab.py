#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.

from . import logging as pc_logging

# import svglib.svglib as svglib
# import reportlab.graphics.renderPM as renderPM
from .sentry import instrument


@instrument(exclude=["is_supported"])
class PluginExportPngReportlab:
    def is_supported(self):
        return True

    def export(self, project, svg_path, width, height, filepath):
        import importlib

        # Load necessary symbols
        svglib = importlib.import_module("svglib.svglib")
        if svglib is None:
            pc_logging.error('Failed to load "svglib". Aborting.')
            return

        renderPM = importlib.import_module("reportlab.graphics.renderPM")
        if renderPM is None:
            pc_logging.error('Failed to load "renderPM". Aborting.')
            return

        # Render the raster image
        drawing = svglib.svg2rlg(svg_path)
        if drawing is None:
            pc_logging.error("Failed to convert to RLG. Aborting.")
            return

        scale_width = float(width) / float(drawing.width)
        scale_height = float(height) / float(drawing.height)
        scale = min(scale_width, scale_height)
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        if not project is None:
            project.ctx.ensure_dirs_for_file(filepath)
        renderPM.drawToFile(
            drawing,
            filepath,
            fmt="PNG",
            configPIL={"transparent": True},
        )
