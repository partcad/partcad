#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .sketch_factory import SketchFactory
from . import logging as pc_logging
from .utils import resolve_resource_path


class SketchFactoryAlias(SketchFactory):
    source_sketch_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action(
            "InitAlias", target_project.name, config["name"]
        ):
            super().__init__(ctx, source_project, target_project, config)
            # Complement the config object here if necessary
            self._create(config)

            if "source" in config:
                self.source_sketch_name = config["source"]
            else:
                self.source_assembly_name = config["name"]
                if not "project" in config:
                    raise Exception(
                        "Alias needs either the source sketch name or the source project name"
                    )

            if "project" in config:
                self.source_project_name = config["project"]
                if (
                    self.source_project_name == "this"
                    or self.source_project_name == ""
                ):
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_sketch_name:
                    self.source_project_name, self.source_sketch_name = (
                        resolve_resource_path(
                            source_project.name,
                            self.source_sketch_name,
                        )
                    )
                else:
                    self.source_project_name = source_project.name
            self.source = (
                self.source_project_name + ":" + self.source_sketch_name
            )

            if self.source_project_name == target_project.name:
                self.sketch.desc = "Alias to %s" % self.source_sketch_name
            else:
                self.sketch.desc = "Alias to %s from %s" % (
                    self.source_sketch_name,
                    self.source_project_name,
                )

            pc_logging.debug("Initializing an alias to %s" % self.source)

    async def instantiate(self, sketch):
        with pc_logging.Action("Alias", sketch.project_name, sketch.name):

            source = self.ctx._get_sketch(self.source)
            shape = source.shape
            if not shape is None:
                return shape

            self.ctx.stats_sketches_instantiated += 1

            if not source.path is None:
                sketch.path = source.path
            return await source.instantiate(sketch)
