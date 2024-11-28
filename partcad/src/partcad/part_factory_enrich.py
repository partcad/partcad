#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import part_config
from . import part_factory as pf
from . import logging as pc_logging
from .utils import resolve_resource_path


class PartFactoryEnrich(pf.PartFactory):
    source_part_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action(
            "InitEnrich", target_project.name, config["name"]
        ):
            super().__init__(ctx, source_project, target_project, config)

            # Determine the part the 'enrich' points to
            if "source" in config:
                self.source_part_name = config["source"]
            else:
                self.source_part_name = config["name"]
                if not "project" in config:
                    raise Exception(
                        "Enrich needs either the source part name or the source project name"
                    )

            if "project" in config:
                self.source_project_name = config["project"]
                if (
                    self.source_project_name == "this"
                    or self.source_project_name == ""
                ):
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_part_name:
                    self.source_project_name, self.source_part_name = (
                        resolve_resource_path(
                            source_project.name,
                            self.source_part_name,
                        )
                    )
                else:
                    self.source_project_name = source_project.name
            self.source = self.source_project_name + ":" + self.source_part_name

            pc_logging.debug("Initializing an enrich to %s" % self.source)

            # TODO(clairbee): Delay de-referencing until part's initialization

            # Get the config of the part the 'enrich' points to
            orig_source_project = source_project
            if self.source_project_name == source_project.name:
                augmented_config = source_project.get_part_config(
                    self.source_part_name
                )
            else:
                source_project = ctx.get_project(self.source_project_name)
                if source_project is None:
                    pc_logging.debug(
                        "Available projects: %s"
                        % str(sorted(list(ctx.projects.keys())))
                    )
                    raise Exception(
                        "Package not found: %s" % self.source_project_name
                    )
                augmented_config = source_project.get_part_config(
                    self.source_part_name
                )
            if augmented_config is None:
                pc_logging.error(
                    "Failed to find the part to enrich: %s"
                    % self.source_part_name
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

            # Fill in the parameter values using the simplified "with" option
            if "with" in config:
                for param in config["with"]:
                    augmented_config["parameters"][param]["default"] = config[
                        "with"
                    ][param]
            orig_source_project.init_part_by_config(
                augmented_config,
                source_project,
            )
