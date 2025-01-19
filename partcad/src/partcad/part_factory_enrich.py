#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import part_config
from . import part_factory as pf
from . import logging as pc_logging
from .utils import resolve_resource_path, get_child_project_path


class PartFactoryEnrich(pf.PartFactory):
    source_part_name: str
    source_project_name: typing.Optional[str]

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitEnrich", target_project.name, config["name"]):
            # Determine the part the 'enrich' points to
            if "source" in config:
                source_part_name = config["source"]
            else:
                source_part_name = config["name"]
                if "project" not in config and "package" not in config:
                    raise Exception("Enrich needs either the source part name or the source project name")

            if "project" in config or "package" in config:
                if "project" in config:
                    source_project_name = config["project"]
                else:
                    source_project_name = config["package"]
                if source_project_name == "this" or source_project_name == "":
                    source_project_name = source_project.name
                elif not source_project_name.startswith("/"):
                    # Resolve the project name relative to the target project
                    source_project_name = get_child_project_path(target_project.name, source_project_name)
            else:
                if ":" in source_part_name:
                    source_project_name, source_part_name = resolve_resource_path(
                        source_project.name,
                        source_part_name,
                    )
                else:
                    source_project_name = source_project.name

            pc_logging.debug(f"Initializing an enrich to {source_project_name}:{source_part_name}")

            super().__init__(ctx, source_project, target_project, config)
            self.source_project = source_project
            self.source_project_name = source_project_name

            if ";" in source_part_name:
                self.source_part_name = source_part_name.split(";")[0]
                suffix = source_part_name.split(";")[1]
                self.extra_with = [p.split("=") for p in suffix.split(",")]
            else:
                self.source_part_name = source_part_name
                self.extra_with = []

            self._create(config)

    async def instantiate(self, part):
        with pc_logging.Action("Enrich", part.project_name, f"{part.name}:{self.source_part_name}"):

            # Get the config of the part the 'enrich' points to
            if self.source_project_name == self.source_project.name:
                augmented_config = self.source_project.get_part_config(self.source_part_name)
            else:
                self.source_project = self.ctx.get_project(self.source_project_name)
                if self.source_project is None:
                    pc_logging.debug("Available projects: %s" % str(sorted(list(self.ctx.projects.keys()))))
                    raise Exception("Package not found: %s" % self.source_project_name)
                augmented_config = self.source_project.get_part_config(self.source_part_name)
            if augmented_config is None:
                pc_logging.error(
                    f"Failed to find the part to enrich: {self.source_project.name}:{self.source_part_name}"
                )
                return

            augmented_config = copy.deepcopy(augmented_config)
            # TODO(clairbee): ideally whatever we pull from the project is already normalized
            augmented_config = part_config.PartConfiguration.normalize(
                self.source_part_name,
                augmented_config,
            )

            # Drop fields we don't want to be inherited by enriched clones
            # TODO(clairbee): keep aliases if they are a function of the orignal name
            if "aliases" in augmented_config:
                del augmented_config["aliases"]

            # Fill in all non-enrich-specific properties from the enrich config into
            # the original config
            for prop_to_copy in part.config:
                if (
                    prop_to_copy == "type"
                    or prop_to_copy == "path"
                    or prop_to_copy == "orig_name"
                    or prop_to_copy == "source"
                    or prop_to_copy == "project"
                    or prop_to_copy == "with"
                ):
                    continue
                augmented_config[prop_to_copy] = part.config[prop_to_copy]

            # See if there are any extra "with" parameters deduced from the source name
            if len(self.extra_with):
                # Create "with" if it wasn't there
                if "with" not in part.config:
                    part.config["with"] = {}

                # The "with" values from the enrich config take precedence over the source name
                for [name, value] in self.extra_with:
                    if name not in part.config["with"]:
                        part.config["with"][name] = value

            # Fill in the parameter values using the simplified "with" option
            if "with" in part.config:
                if "parameters" not in augmented_config:
                    raise Exception(
                        "Attempting to parametrize a part that has no parameters: %s" % str(augmented_config)
                    )
                for param in part.config["with"]:
                    if param not in augmented_config["parameters"]:
                        raise Exception(
                            "Attempting to parametrize a part with an unknown parameter: %s:%s: %s"
                            % (self.source_project_name, self.source_part_name, param)
                        )
                    desired_type = type(augmented_config["parameters"][param]["default"])
                    augmented_config["parameters"][param]["default"] = desired_type(part.config["with"][param])

            self.source_project.init_part_by_config(augmented_config, self.source_project)

            source = self.source_project.get_part(part.name)
            name = part.config["name"]
            part.config = source.config
            part.config["source"] = self.source_project_name + ":" + self.source_part_name
            part.config["orig_name"] = part.name
            part.config["name"] = name

            # Clone the source object properties
            if source.path:
                part.path = source.path
            if "with" in source.config:
                self.hash.add_dict(part.config["with"])
            part.cachable = source.cachable
            part.cache_dependencies = source.cache_dependencies
            part.cache_dependencies_broken = source.cache_dependencies_broken

            _wrapped = source._wrapped
            if _wrapped:
                part._wrapped = _wrapped
                return _wrapped

            self.ctx.stats_parts_instantiated += 1

            return await source.instantiate(part)
