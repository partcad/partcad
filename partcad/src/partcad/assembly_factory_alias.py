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

from . import assembly_factory as pf
from . import logging as pc_logging
from .utils import resolve_resource_path, get_child_project_path


class AssemblyFactoryAlias(pf.AssemblyFactory):
    source_assembly_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitAlias", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            # Complement the config object here if necessary
            self._create(config)

            self.assembly.get_cacheable = self.get_cacheable

            if "source" in config:
                self.source_assembly_name = config["source"]
            else:
                self.source_assembly_name = config["name"]
                if "project" not in config and "package" not in config:
                    raise Exception("Alias needs either the source assembly name or the source project name")

            if "project" in config or "package" in config:
                if "project" in config:
                    self.source_project_name = config["project"]
                else:
                    self.source_project_name = config["package"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = self.project.name
                elif not self.source_project_name.startswith("//"):
                    # Resolve the project name relative to the target project
                    self.source_project_name = get_child_project_path(target_project.name, self.source_project_name)
            else:
                if ":" in self.source_assembly_name:
                    self.source_project_name, self.source_assembly_name = resolve_resource_path(
                        self.project.name,
                        self.source_assembly_name,
                    )
                else:
                    self.source_project_name = self.project.name
            self.source = self.source_project_name + ":" + self.source_assembly_name
            config["source_resolved"] = self.source

            if self.source_project_name == self.project.name:
                self.assembly.desc = "Alias to %s" % self.source_assembly_name
            else:
                self.assembly.desc = "Alias to %s from %s" % (
                    self.source_assembly_name,
                    self.source_project_name,
                )

            pc_logging.debug("Initializing an alias to %s" % self.source)

    def instantiate(self, obj):
        with pc_logging.Action("Alias", obj.project_name, f"{obj.name}:{self.source_assembly_name}"):
            source = self.ctx._get_assembly(self.source)
            if not source:
                pc_logging.error(f"The alias source {self.source} is not found")
                return

            # Clone the source object properties
            if source.path:
                obj.path = source.path
            obj.cacheable = source.cacheable
            obj.cache_dependencies = copy.copy(source.cache_dependencies)
            obj.cache_dependencies_broken = source.cache_dependencies_broken

            children = source.children
            if children:
                obj.children = children
                obj._wrapped = source._wrapped
                return

            self.ctx.stats_assemblies_instantiated += 1

            source.instantiate(obj)

    def get_cacheable(self) -> bool:
        # This object is a wrapper around another one.
        # The other one is the one which must be cached.
        return False
