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
    ENRICH_ONLY_PROPERTIES,
    INSTANCE_APPLIED_PROPERTIES,
    enriched_source_name,
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
            config = copy.copy(config)
            config["source"] = enriched_source_name(source_project, target_project, config)
            warn_about_ignored_properties(target_project, config, config["source"])
            # Fully qualified now, so the package it names must not be applied
            # to it a second time by the alias this hands the work to.
            config.pop("package", None)
            config.pop("project", None)
            super().__init__(ctx, source_project, target_project, config)

    async def instantiate(self, part):
        with pc_logging.Action("Enrich", part.project_name, f"{part.name}:{self.source_part_name}"):
            source = self.ctx._get_part(self.source)
            if source is None:
                raise Exception(f"Failed to find the part to enrich: {self.source}")

            # Unlike a plain alias, an enrich reports the parameters it resolved
            # to: those values are what was asked for, and 'pc info' and the
            # assemblies that use it read them from here. What it declares
            # itself - 'desc', 'offset', whatever else - stays its own, since
            # that describes this object and not the instance it shares with
            # every other enrich that asks for the same parameters.
            # The *final* config of the source, so that an enrich pointing
            # at an alias - or at a chain of them - reports what is at the end
            # of it rather than the reference in the middle.
            enrich_config = part.config
            part.config = {
                key: value for key, value in source.get_final_config().items() if key not in INSTANCE_APPLIED_PROPERTIES
            }
            for prop_to_copy in enrich_config:
                if prop_to_copy in ENRICH_ONLY_PROPERTIES:
                    continue
                part.config[prop_to_copy] = enrich_config[prop_to_copy]
            part.config["source"] = self.source
            part.config["orig_name"] = part.name
            part.config["name"] = enrich_config["name"]

            return await super().instantiate(part)
