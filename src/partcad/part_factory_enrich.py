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

from . import part_factory_alias as pfa
from . import logging as pc_logging
from .enrich import (
    adopt_source_config,
    enriched_source_name,
    resolve_source_again,
    warn_about_ignored_properties,
)

from . import telemetry


@telemetry.instrument()
class PartFactoryEnrich(pfa.PartFactoryAlias):
    """An 'enrich' is an alias to a parameterized instance of what it enriches.

    Both halves of that already exist. A package makes an instance of its own
    object with other parameter values whenever one is asked for by name
    ('cube;width=20.0' - see 'Project.get_object'), and an alias makes an object
    available under a name of its own. So an enrich needs no machinery beyond
    working out which instance its 'with' asks for, and being an alias to it.

    That is also what decides where the two objects live, which is what used to
    go wrong here. The instance belongs to the package that declares the object
    it is an instance of, under a name that says which instance it is; this
    object, carrying the enrich's own name, belongs to the package that
    declares the enrich, where its assemblies refer to it as a local part. It
    used to be the instance that was registered in the source package under the
    *enriching* name - which defaults to the source object's own name - so
    enriching an object replaced it.

    Working out the source in the constructor, rather than while instantiating,
    is what makes a chain of enriches and aliases work in any order: what an
    enrich points at is decided by its own declaration and not by who is asking
    for it.
    """

    source_part_name: str
    source_project_name: typing.Optional[str]

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitEnrich", target_project.name, config["name"]):
            source = enriched_source_name(source_project, target_project, config)
            warn_about_ignored_properties(target_project, config, source)
            # What it resolved to, recorded on the declaration itself the way an
            # alias records it: 'pc convert' follows the stored configuration
            # rather than the object, and the 'package:' shorthand leaves it
            # nothing else to follow.
            config["source_resolved"] = source

            # The declaration as written, kept so that what this points at can
            # be worked out again once everything is declared (see
            # 'resolve_source_again'). What is handed to the alias below is a
            # copy, with the reference spelled out in it.
            self.enrich_declaration = config
            config = copy.copy(config)
            config["source"] = source
            # Fully qualified now, so the package it names must not be applied
            # to it a second time by the alias this hands the work to.
            config.pop("package", None)
            config.pop("project", None)
            super().__init__(ctx, source_project, target_project, config)

    async def prepare_async(self, part) -> None:
        # Before anything is resolved: the user's own parameter overrides may
        # have arrived after this package was loaded, and they say which
        # instance of the source this wants.
        resolve_source_again(self, self.enrich_declaration, "source_part_name")
        await super().prepare_async(part)

        # What this object reports, settled here rather than while it is built:
        # a shape that comes out of the cache is never instantiated, and an
        # enrich has to answer the same either way (see 'adopt_source_config').
        source = self.ctx._get_part(self.source)
        if source is None:
            raise Exception(f"Failed to find the part to enrich: {self.source}")
        adopt_source_config(part, source, self.source)

    async def instantiate(self, part):
        with pc_logging.Action("Enrich", part.project_name, f"{part.name}:{self.source_part_name}"):
            return await super().instantiate(part)
