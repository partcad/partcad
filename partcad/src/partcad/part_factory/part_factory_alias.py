#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-22
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from partcad.part_factory.part_factory import PartFactory
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import get_child_project_path, resolve_resource_path
from partcad import logging as pc_logging



ALIAS = PartTypes.ALIAS

@register_factory(ALIAS.type)
class PartFactoryAlias(PartFactory):
    source_part_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action(f"Init{ALIAS.type.capitalize()}", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

            self.part.get_final_config = self.get_final_config
            self.part.get_cacheable = self.get_cacheable

            # Determine source part name
            self.source_part_name = config.get("source", config["name"])

            # Determine source project name
            project_or_package = config.get("project") or config.get("package")
            if project_or_package is not None:
                self.source_project_name = project_or_package or source_project.name
                if self.source_project_name == "this":
                    self.source_project_name = source_project.name
                elif not self.source_project_name.startswith("//"):
                    self.source_project_name = get_child_project_path(
                        target_project.name, self.source_project_name
                    )
            elif ":" in self.source_part_name:
                self.source_project_name, self.source_part_name = resolve_resource_path(
                    source_project.name,
                    self.source_part_name,
                )
            else:
                self.source_project_name = source_project.name

            # Compose full source identifier
            self.source = f"{self.source_project_name}:{self.source_part_name}"
            config["source_resolved"] = self.source

            # Update description
            if self.source_project_name == target_project.name:
                self.part.desc = f"Alias to {self.source_part_name}"
            else:
                self.part.desc = f"Alias to {self.source_part_name} from {self.source_project_name}"

            pc_logging.debug(f"Initializing an alias to {self.source}")

    async def instantiate(self, obj):
        with pc_logging.Action("Alias", obj.project_name, f"{obj.name}:{self.source_part_name}"):
            source = self.ctx._get_part(self.source)
            if not source:
                raise Exception(f"The alias source {self.source} is not found")

            # Clone the source object properties
            if source.path:
                obj.path = source.path
            obj.cacheable = source.cacheable
            obj.cache_dependencies = copy.copy(source.cache_dependencies)
            obj.cache_dependencies_broken = source.cache_dependencies_broken

            if source._wrapped:
                obj._wrapped = source._wrapped
                return source._wrapped

            self.ctx.stats_parts_instantiated += 1
            return await source.instantiate(obj)

    def get_final_config(self):
        source = self.ctx._get_part(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        return source.get_final_config()

    def get_cacheable(self) -> bool:
        # This object is a wrapper around another one.
        # The other one is the one which must be cached.
        return False
