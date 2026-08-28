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

from . import telemetry
from . import assembly_factory as pf
from . import logging as pc_logging
from .utils import format_parameterized_name, get_child_project_path


@telemetry.instrument()
class AssemblyFactoryAlias(pf.AssemblyFactory):
    source_assembly_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitAlias", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            # Complement the config object here if necessary
            self._create(config)

            self.assembly.get_final_config = self.get_final_config
            self.assembly.get_cacheable = self.get_cacheable

            # A reference has no cache key of its own until it has taken the
            # one of the object it points at (see 'prepare_async').
            self.keyed = False

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
                    self.source_project_name, self.source_assembly_name = self.project.resolve(
                        self.source_assembly_name,
                    )
                else:
                    self.source_project_name = self.project.name
            # Parameters handed to an alias are passed on to what it points
            # at: an alias declares none of its own to apply them to. See
            # 'PartFactoryAlias' for what that makes possible.
            if config.get("with"):
                self.source_assembly_name = format_parameterized_name(self.source_assembly_name, config["with"])

            self.source = self.source_project_name + ":" + self.source_assembly_name
            config["source_resolved"] = self.source

            if self.source_project_name == self.project.name:
                self.assembly.desc = "Alias to %s" % self.source_assembly_name
            else:
                self.assembly.desc = "Alias to %s from %s" % (
                    self.source_assembly_name,
                    self.source_project_name,
                )

            # pc_logging.debug("Initialized an alias to %s" % self.source)

    async def prepare_async(self, obj) -> None:
        """Resolve the source, then prepare it.

        Resolving is the point: the source may live in another package, and
        asking the context for it loads - and so downloads - that package.
        """
        source = self.ctx._get_assembly(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        await source.prepare_async()

        # What this object is, taken from what it points at: its cache key, and
        # the properties that say where the geometry came from. Here rather
        # than in 'instantiate()' because an assembly that comes out of the
        # cache is never assembled, and this is what tells it which entry that
        # is.
        await obj.take_cache_key_from(source)
        # Unlike a part or a sketch, which hand back what the source built, this
        # object builds its own envelope out of the source's children (see
        # 'instantiate'), so it is the one that fills the entry they share -
        # otherwise nothing fills it unless the source is asked for directly.
        # Two references writing it write the same payload: what the cache
        # stores is the geometry, and the name and placement around it are
        # stripped on the way in.
        obj.owns_cache_entry = True
        self.keyed = True
        if source.path:
            obj.path = source.path
        obj.cacheable = source.cacheable and obj.cacheable
        obj.cache_dependencies = copy.copy(source.cache_dependencies)
        obj.cache_dependencies_broken = source.cache_dependencies_broken

    def instantiate(self, obj):
        with pc_logging.Action("Alias", obj.project_name, f"{obj.name}:{self.source_assembly_name}"):
            source = self.ctx._get_assembly(self.source)
            if not source:
                pc_logging.error(f"The alias source {self.source} is not found")
                return

            # Let the source assemble itself, and take the children it has.
            # Assembling it against this object instead - which is what used to
            # happen - read the same ASSY file and resolved the same tree once
            # per reference, and left the source itself unassembled.
            #
            # The children are the pieces, not the geometry: this object still
            # builds its own envelope out of them, in its own name and with its
            # own placement, and each piece hands back the one shape it has
            # (see 'Shape.get_wrapped').
            # Under the source's lock: two references can otherwise both find
            # it empty and assemble it, and the ASSY factory appends to
            # 'children' rather than replacing them, so the tree would end up in
            # there twice.
            with source.lock:
                if not source.children:
                    source.instantiate(source)
                obj.children = source.children

    def get_final_config(self):
        source = self.ctx._get_assembly(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        return source.get_final_config()

    def get_cacheable(self) -> bool:
        # Cacheable once it knows which entry it shares: a reference keys on
        # the object it points at, and has nothing to be looked up or stored
        # under before it has resolved it (see 'prepare_async').
        obj = self.assembly
        return self.keyed and obj.cacheable and not obj.get_cache_dependencies_broken()
