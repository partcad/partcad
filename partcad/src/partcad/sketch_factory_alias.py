#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .sketch_factory import SketchFactory
from . import logging as pc_logging
from .utils import resolve_resource_path, get_child_project_path


class SketchFactoryAlias(SketchFactory):
    source_sketch_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitAlias", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            # Complement the config object here if necessary
            self._create(config)

            if "source" in config:
                self.source_sketch_name = config["source"]
            else:
                self.source_sketch_name = config["name"]
                if "project" not in config and "package" not in config:
                    raise Exception("Alias needs either the source sketch name or the source project name")

            if "project" in config or "package" in config:
                if "project" in config:
                    self.source_project_name = config["project"]
                else:
                    self.source_project_name = config["package"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
                elif not self.source_project_name.startswith("/"):
                    # Resolve the project name relative to the target project
                    self.source_project_name = get_child_project_path(target_project.name, self.source_project_name)
            else:
                if ":" in self.source_sketch_name:
                    self.source_project_name, self.source_sketch_name = resolve_resource_path(
                        source_project.name,
                        self.source_sketch_name,
                    )
                else:
                    self.source_project_name = source_project.name
            self.source = self.source_project_name + ":" + self.source_sketch_name

            if self.source_project_name == target_project.name:
                self.sketch.desc = "Alias to %s" % self.source_sketch_name
            else:
                self.sketch.desc = "Alias to %s from %s" % (
                    self.source_sketch_name,
                    self.source_project_name,
                )

            pc_logging.debug("Initializing an alias to %s" % self.source)

    async def instantiate(self, sketch):
        with pc_logging.Action("Alias", sketch.project_name, f"{sketch.name}:{self.source_sketch_name}"):

            source = self.ctx._get_sketch(self.source)
            if not source:
                pc_logging.error(f"The alias source {self.source} is not found")
                return None

            shape = source.shape
            if shape:
                sketch.shape = shape
                return shape

            self.ctx.stats_sketches_instantiated += 1

            if source.path:
                sketch.path = source.path
            return await source.instantiate(sketch)
