#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import cadquery as cq

from . import logging as pc_logging
from .sketch_factory_file import SketchFactoryFile


class SketchFactoryDxf(SketchFactoryFile):
    tolerance = 0.000001
    include = []
    exclude = []

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitDXF", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".dxf",
            )

            if "tolerance" in config:
                self.tolerance = float(config["tolerance"])

            if "include" in config:
                if isinstance(config["include"], list):
                    self.include = config["include"]
                elif isinstance(config["include"], str):
                    self.include = [config["include"]]

            if "exclude" in config:
                if isinstance(config["exclude"], list):
                    self.exclude = config["exclude"]
                elif isinstance(config["exclude"], str):
                    self.exclude = [config["exclude"]]

            self._create(config)

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("DXF", sketch.project_name, sketch.name):
            try:
                workplane = cq.importers.importDXF(
                    self.path,
                    tol=self.tolerance,
                    include=self.include,
                    exclude=self.exclude,
                )
                shape = workplane.val().wrapped
            except Exception as e:
                pc_logging.exception(
                    "Failed to import the DXF file: %s: %s" % (self.path, e)
                )
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
