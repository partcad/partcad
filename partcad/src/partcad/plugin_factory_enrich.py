#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from .plugin_config import PluginConfiguration
from .plugin_factory import PluginFactory
from . import logging as pc_logging
from .utils import resolve_resource_path
from . import telemetry


@telemetry.instrument()
class PluginFactoryEnrich(PluginFactory):
    source_plugin_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitEnrich", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            # Determine the plugin the 'enrich' points to
            if "source" in config:
                self.source_plugin_name = config["source"]
            else:
                self.source_plugin_name = config["name"]
                if not "project" in config:
                    raise Exception("Enrich needs either the source plugin name or the source project name")

            if "project" in config:
                self.source_project_name = config["project"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_plugin_name:
                    self.source_project_name, self.source_plugin_name = resolve_resource_path(
                        source_project.name,
                        self.source_plugin_name,
                    )
                else:
                    self.source_project_name = source_project.name
            self.source = self.source_project_name + ":" + self.source_plugin_name

            # pc_logging.debug("Initialized an enrich to %s" % self.source)

            # TODO(clairbee): Delay de-referencing until plugin's initialization

            # Get the config of the plugin the 'enrich' points to
            if self.source_project_name == source_project.name:
                augmented_config = self.get_source_config(self.source_plugin_name)
            else:
                source_project = ctx.get_project(self.source_project_name)
                if source_project is None:
                    pc_logging.debug("Available projects: %s" % str(sorted(list(ctx.projects.keys()))))
                    raise Exception("Package not found: %s" % self.source_project_name)
                augmented_config = self.get_source_config(self.source_plugin_name, source_project=source_project)
            if augmented_config is None:
                pc_logging.error("Failed to find the plugin to enrich: %s" % self.source_plugin_name)
                return

            target_provider_name = f"{self.target_project.name}:{self.name}"

            augmented_config = copy.deepcopy(augmented_config)
            # TODO(clairbee): ideally whatever we pull from the project is already normalized
            augmented_config = PluginConfiguration.normalize(
                self.source_plugin_name, augmented_config, target_provider_name
            )

            # Fill in the parameter values using the simplified "with" option
            if "with" in config:
                for param in config["with"]:
                    augmented_config["parameters"][param]["default"] = config["with"][param]

            # Recalling normalize to normalize data after replacing target parameters from with key.
            augmented_config = PluginConfiguration.normalize(
                self.source_provider_name, augmented_config, target_provider_name
            )

            # Drop fields we don't want to be inherited by enriched clones
            # TODO(clairbee): keep aliases if they are a function of the original name
            if "aliases" in augmented_config:
                del augmented_config["aliases"]

            # Fill in all non-enrich-specific properties from the enrich config into
            # the original config
            for prop_to_copy in config:
                if (
                    prop_to_copy == "type"
                    or prop_to_copy == "path"
                    or prop_to_copy == "orig_name"
                    or prop_to_copy == "source"
                    or prop_to_copy == "project"
                    or prop_to_copy == "with"
                ):
                    continue
                augmented_config[prop_to_copy] = config[prop_to_copy]

            self.init_source_by_config(augmented_config)

    def init_source_by_config(self, augmented_config):
        raise NotImplementedError("PluginFactoryEnrich.init_source_by_config must be implemented in a subclass")

    def get_source_config(self, source_plugin_name: str, source_project=None):
        raise NotImplementedError("PluginFactoryEnrich.get_source_config must be implemented in a subclass")
