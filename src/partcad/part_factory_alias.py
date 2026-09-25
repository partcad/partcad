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

from . import logging as pc_logging
from . import part_factory as pf
from . import reference, telemetry
from .shape_config_store import resolve_store_properties
from .utils import format_parameterized_name


@telemetry.instrument()
class PartFactoryAlias(pf.PartFactory):
    source_part_name: str
    source_project_name: typing.Optional[str]
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitAlias", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            # Complement the config object here if necessary
            self._create(config)

            self.part.get_final_config = self.get_final_config
            self.part.get_cacheable = self.get_cacheable
            self.part.get_tolerance = self.get_tolerance

            # A reference has no cache key of its own until it has taken the
            # one of the object it points at (see 'prepare_async'), and is not
            # cacheable before that: what it would hash until then is its own
            # 'offset', which identifies nothing.
            self.keyed = False

            # Where this points, by the rules every reference spells it with
            # (see 'partcad.reference'). Recorded on the declaration as well,
            # because 'pc convert' follows the stored configuration rather than
            # the object, and a listing reads its description off it without
            # building anything.
            self.source = reference.source_of(source_project, target_project.name, config, "part")
            self.source_project_name, self.source_part_name = reference.split(self.source)
            # Parameters handed to an alias are passed on to what it points
            # at. An alias declares no parameters of its own, so it has nothing
            # to apply them to - it is a reference, and a reference to an object
            # with other parameter values is a reference to another instance of
            # it. This is what lets aliases and enriches be chained in any
            # order: the parameters travel down the chain until they reach the
            # object that declares them ('Project.get_object' puts them in
            # 'with' when it parametrizes a reference).
            if config.get("with"):
                self.source_part_name = format_parameterized_name(self.source_part_name, config["with"])
                self.source = self.source_project_name + ":" + self.source_part_name
            config["source_resolved"] = self.source

            self.part.desc = reference.describe(config["type"], target_project.name, self.source)

            # pc_logging.debug("Initialized an alias to %s" % self.source)

    async def prepare_async(self, obj) -> None:
        """Resolve the source, then prepare it.

        Resolving is the point: the source may live in another package, and
        asking the context for it loads - and so downloads - that package.
        """
        source = await self.ctx._get_part_async(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        await source.prepare_async()

        # What this object is, taken from what it points at: its key, and the
        # properties that describe where the geometry came from. Here rather
        # than in 'instantiate()' because a shape that comes out of the cache
        # is never instantiated, and this is what tells it which entry that is.
        await obj.take_cache_key_from(source)
        self.keyed = True
        if source.path:
            obj.path = source.path
        obj.cacheable = source.cacheable and obj.cacheable
        obj.cache_dependencies = copy.copy(source.cache_dependencies)
        obj.cache_dependencies_broken = source.cache_dependencies_broken

    async def instantiate(self, obj):
        with pc_logging.Action("Alias", obj.project_name, f"{obj.name}:{self.source_part_name}"):

            source = await self.ctx._get_part_async(self.source)
            if not source:
                pc_logging.error(f"The alias source {self.source} is not found")
                return None

            # Ask the source object to materialize itself, rather than running
            # its factory against this one. The source is a single object, and
            # everything pointing at it - every alias, and so every enrich -
            # has to get the geometry it has rather than build another copy of
            # it. Running the factory here left the source's own '_wrapped'
            # unset, so the next reference to it built it again, and it also
            # skipped the source's cache entry, which is the only one there is:
            # a reference is not cacheable in its own right.
            #
            # This object then wraps what came back in its own name and applies
            # its own 'offset'/'scale' to it, which is what 'get_wrapped()'
            # does with whatever a factory returns.
            wrapped = await source.get_wrapped(self.ctx)
            # The pieces a compound or an assembly reports separately from its
            # own shape, which the source resolved along with it.
            obj.components = copy.copy(source.components)
            return wrapped

    def get_final_config(self):
        """The declaration this reference resolves to, as this reference reports it.

        The source's, but for the purchasing record: a reference may name a
        vendor and an SKU of its own, and that is the one thing about the object
        it is allowed to restate (see 'resolve_store_properties'). Applied here
        rather than where the record is read, so that it travels: an alias of an
        alias, and an enrich of an enrich, resolve through this same method and
        so see what the reference below them declared rather than only what the
        object at the end of the chain did.

        And for how the object is *made*, which a reference may state for the
        same reason: one piece of geometry is made different ways by different
        packages. A 4x4 post is lumber in the package that defines lumber and a
        board cut to length off a store's eight foot one in the package that
        builds a desk from it -- which is what an enrich of it is for. A
        'manufacturing:' section is one statement (a method, a stock, a machine
        and where it cuts), so a reference that writes one replaces the
        source's whole rather than key by key.
        """
        source = self.ctx._get_part(self.source)
        if not source:
            raise Exception(f"The alias source {self.source} is not found")
        resolved = resolve_store_properties(source.get_final_config(), self.config)
        manufacturing = self.config.get("manufacturing") if isinstance(self.config, dict) else None
        if manufacturing:
            resolved = dict(resolved)
            resolved["manufacturing"] = manufacturing
        return resolved

    async def get_tolerance(self):
        """How precisely the object this points at has to be made.

        The source's answer, because a reference declares no tolerance of its
        own -- it has no file to read one from and no object-type parameters to
        state one in -- and the geometry it stands for is the source's. Without
        this every alias and every enrich of a part that is *made* answered
        None, which the manufacturability test reads as a part type that cannot
        say, and failed.
        """
        source = await self.ctx._get_part_async(self.source)
        if not source:
            return None
        return await source.get_tolerance()

    def get_cacheable(self) -> bool:
        # Cacheable once it knows which entry it shares: a reference keys on
        # the object it points at, and has nothing to be looked up or stored
        # under before it has resolved it (see 'prepare_async'). What it says
        # about itself still applies - 'cache: false' on a reference is the
        # user asking for this object not to be cached.
        obj = self.part
        return self.keyed and obj.cacheable and not obj.get_cache_dependencies_broken()
