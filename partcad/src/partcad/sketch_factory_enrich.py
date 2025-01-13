#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import sketch_config
from . import sketch_factory as pf
from . import logging as pc_logging
from .utils import resolve_resource_path


class SketchFactoryEnrich(pf.SketchFactory):
    source_sketch_name: str
    source_project_name: typing.Optional[str]

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitEnrich", target_project.name, config["name"]):
            # Determine the sketch the 'enrich' points to
            if "source" in config:
                source_sketch_name = config["source"]
            else:
                source_sketch_name = config["name"]
                if "project" not in config:
                    raise Exception("Enrich needs either the source sketch name or the source project name")

            if "project" in config:
                source_project_name = config["project"]
                if source_project_name == "this" or source_project_name == "":
                    source_project_name = source_project.name
            else:
                if ":" in source_sketch_name:
                    source_project_name, source_sketch_name = resolve_resource_path(
                        source_project.name,
                        source_sketch_name,
                    )
                else:
                    source_project_name = source_project.name

            pc_logging.debug(f"Initializing an enrich to {source_project_name}:{source_sketch_name}")

            super().__init__(ctx, source_project, target_project, config)
            self.source_project = source_project
            self.source_project_name = source_project_name

            if ";" in source_sketch_name:
                self.source_sketch_name = source_sketch_name.split(";")[0]
                suffix = source_sketch_name.split(";")[1]
                self.extra_with = [p.split("=") for p in suffix.split(",")]
            else:
                self.source_sketch_name = source_sketch_name
                self.extra_with = []

            self._create(config)

    async def instantiate(self, sketch):
        with pc_logging.Action("Enrich", sketch.project_name, sketch.name):

            # Get the config of the sketch the 'enrich' points to
            if self.source_project_name == self.source_project.name:
                augmented_config = self.source_project.get_sketch_config(self.source_sketch_name)
            else:
                self.source_project = self.ctx.get_project(self.source_project_name)
                if self.source_project is None:
                    pc_logging.debug("Available projects: %s" % str(sorted(list(self.ctx.projects.keys()))))
                    raise Exception("Package not found: %s" % self.source_project_name)
                augmented_config = self.source_project.get_sketch_config(self.source_sketch_name)
            if augmented_config is None:
                pc_logging.error(
                    f"Failed to find the sketch to enrich: {self.source_project.name}:{self.source_sketch_name}"
                )
                return

            augmented_config = copy.deepcopy(augmented_config)
            # TODO(clairbee): ideally whatever we pull from the project is already normalized
            augmented_config = sketch_config.SketchConfiguration.normalize(
                self.source_sketch_name,
                augmented_config,
            )

            # Drop fields we don't want to be inherited by enriched clones
            # TODO(clairbee): keep aliases if they are a function of the orignal name
            if "aliases" in augmented_config:
                del augmented_config["aliases"]

            # Fill in all non-enrich-specific properties from the enrich config into
            # the original config
            for prop_to_copy in sketch.config:
                if (
                    prop_to_copy == "type"
                    or prop_to_copy == "path"
                    or prop_to_copy == "orig_name"
                    or prop_to_copy == "source"
                    or prop_to_copy == "project"
                    or prop_to_copy == "with"
                ):
                    continue
                augmented_config[prop_to_copy] = sketch.config[prop_to_copy]

            # See if there are any extra "with" parameters deduced from the source name
            if len(self.extra_with):
                # Create "with" if it wasn't there
                if "with" not in sketch.config:
                    sketch.config["with"] = {}

                # The "with" values from the enrich config take precedence over the source name
                for [name, value] in self.extra_with:
                    if name not in sketch.config["with"]:
                        sketch.config["with"][name] = value

            # Fill in the parameter values using the simplified "with" option
            if "with" in sketch.config:
                if "parameters" not in augmented_config:
                    raise Exception(
                        "Attempting to parametrize a sketch that has no parameters: %s" % str(augmented_config)
                    )
                for param in sketch.config["with"]:
                    if param not in augmented_config["parameters"]:
                        raise Exception(
                            "Attempting to parametrize a sketch with an unknown parameter: %s:%s: %s"
                            % (self.source_project_name, self.source_sketch_name, param)
                        )
                    augmented_config["parameters"][param]["default"] = sketch.config["with"][param]

            self.source_project.init_sketch_by_config(augmented_config)

            source = self.source_project.get_sketch(sketch.name)
            name = sketch.config["name"]
            sketch.config = source.config
            sketch.config["source"] = self.source_project_name + ":" + self.source_sketch_name
            sketch.config["orig_name"] = sketch.name
            sketch.config["name"] = name
            shape = source.shape
            if shape is not None:
                sketch.shape = shape
                return shape

            self.ctx.stats_sketches_instantiated += 1

            if source.path is not None:
                sketch.path = source.path
            return await source.instantiate(sketch)
