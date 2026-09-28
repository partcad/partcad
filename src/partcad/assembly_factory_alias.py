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
from . import reference, telemetry
from .shape_config_store import resolve_store_properties
from .utils import format_parameterized_name


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

            # Where this points, by the rules every reference spells it with
            # (see 'partcad.reference'). Recorded on the declaration as well,
            # because 'pc convert' follows the stored configuration rather than
            # the object, and a listing reads its description off it without
            # building anything.
            self.source = reference.source_of(source_project, target_project.name, config, "assembly")
            self.source_project_name, self.source_assembly_name = reference.split(self.source)
            # Parameters handed to an alias are passed on to what it points
            # at. An alias declares no parameters of its own, so it has nothing
            # to apply them to - it is a reference, and a reference to an object
            # with other parameter values is a reference to another instance of
            # it. This is what lets aliases and enriches be chained in any
            # order: the parameters travel down the chain until they reach the
            # object that declares them ('Project.get_object' puts them in
            # 'with' when it parametrizes a reference).
            if config.get("with"):
                self.source_assembly_name = format_parameterized_name(self.source_assembly_name, config["with"])
                self.source = self.source_project_name + ":" + self.source_assembly_name
            config["source_resolved"] = self.source

            self.assembly.desc = config.get("desc") or reference.describe(
                config["type"], target_project.name, self.source
            )

            # pc_logging.debug("Initialized an alias to %s" % self.source)

    async def prepare_async(self, obj) -> None:
        """Resolve the source, then prepare it.

        Resolving is the point: the source may live in another package, and
        asking the context for it loads - and so downloads - that package.
        """
        source = self.get_source_object(self.source)
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

    async def subassemblies_async(self, assembly) -> list:
        """What this points at: building that is what builds this.

        One object, not its contents - it answers the same question about
        itself when it is asked for. An enrich is an alias to a parameterized
        instance and so needs nothing of its own here; by the time this is read
        'prepare_async()' has resolved which instance that is.
        """
        source = self.get_source_object(self.source)
        return [source] if source is not None else []

    def instantiate(self, obj):
        with pc_logging.Action("Alias", obj.project_name, f"{obj.name}:{self.source_assembly_name}"):
            source = self.get_source_object(self.source)
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
        """The declaration this reference resolves to, as this reference reports it.

        The source's, but for the purchasing record this reference may state of
        its own - an assembly is bought or put together the same way a part is.
        See 'PartFactoryAlias.get_final_config' for why it is resolved here.
        """
        source = self.get_source_object(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        return resolve_store_properties(source.get_final_config(), self.config)

    def get_cacheable(self) -> bool:
        # Cacheable once it knows which entry it shares: a reference keys on
        # the object it points at, and has nothing to be looked up or stored
        # under before it has resolved it (see 'prepare_async').
        obj = self.assembly
        return self.keyed and obj.cacheable and not obj.get_cache_dependencies_broken()
