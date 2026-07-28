#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import os
import sys

from .part_factory import PartFactory
from .sketch import Sketch
from . import logging as pc_logging

from . import telemetry

# This factory builds the solid in-process, so it needs the sketch as a live
# shape; get_wrapped() returns a BREP envelope, so decode it with the sandbox
# codec. 'ocp_serialize' is import-safe (it imports OCP lazily); the direct OCP
# imports are made lazily in instantiate() so this module stays off the
# 'import partcad' OCP path.
sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
import ocp_serialize


@telemetry.instrument()
class PartFactoryExtrude(PartFactory):
    depth: float
    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str
    sketch: Sketch

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("IniExtrude", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )

            self.depth = float(config["depth"])

            self.source_sketch_name = config.get("sketch", "sketch")
            if "project" in config:
                self.source_project_name = config["project"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_sketch_name:
                    self.source_project_name, self.source_sketch_name = source_project.resolve(
                        self.source_sketch_name,
                    )
                else:
                    self.source_project_name = source_project.name
            self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name

            self._create(config)
            self.part.hash.add_string(str(self.depth))
            # TODO(clairbee): add dependency tracking for Extrude (PC-313)
            self.part.cache_dependencies_broken = True

    async def instantiate(self, part):
        with pc_logging.Action("Extrude", part.project_name, part.name):
            shape = None
            try:
                from OCP.gp import gp_Vec
                from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

                self.sketch = self.ctx.get_sketch(self.source_sketch_spec)

                sketch_shape = ocp_serialize.decode_shape(await self.sketch.get_wrapped(self.ctx))
                maker = BRepPrimAPI_MakePrism(
                    sketch_shape,
                    gp_Vec(0.0, 0.0, self.depth),
                )
                maker.Build()
                shape = maker.Shape()
            except Exception as e:
                pc_logging.exception("Failed to create an extruded part: %s" % e)

            self.ctx.stats_parts_instantiated += 1

            return shape
