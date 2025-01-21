#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from OCP.gp import (
    gp_Vec,
)
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakePrism,
)

from .part_factory import PartFactory
from .sketch import Sketch
from . import logging as pc_logging
from .utils import resolve_resource_path

from .sentry import instrument


@instrument()
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
                    self.source_project_name, self.source_sketch_name = resolve_resource_path(
                        source_project.name,
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
                self.sketch = self.ctx.get_sketch(self.source_sketch_spec)

                maker = BRepPrimAPI_MakePrism(
                    await self.sketch.get_wrapped(self.ctx),
                    gp_Vec(0.0, 0.0, self.depth),
                )
                maker.Build()
                shape = maker.Shape()
            except Exception as e:
                pc_logging.exception("Failed to create an extruded part: %s" % e)

            self.ctx.stats_parts_instantiated += 1

            return shape
