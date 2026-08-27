#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import assembly_factory_alias as afa
from . import logging as pc_logging
from .enrich import (
    adopt_source_config,
    enriched_source_name,
    resolve_source_again,
    warn_about_ignored_properties,
)
from . import telemetry


@telemetry.instrument()
class AssemblyFactoryEnrich(afa.AssemblyFactoryAlias):
    """An alias to a parameterized instance of the assembly it enriches.

    An assembly takes parameters like anything else - an ASSY file is a
    template, and the values reach it as 'param_<name>' (see
    'AssemblyFactoryAssy.read_assy') - so an assembly can be enriched like
    anything else, and it means the same thing: the assembly of that package,
    assembled with other values.

    See 'PartFactoryEnrich' for why that is the whole of what an enrich has to
    do, and for where each of the two objects involved ends up.
    """

    source_assembly_name: str
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

    async def prepare_async(self, assembly) -> None:
        # Before anything is resolved: the user's own parameter overrides may
        # have arrived after this package was loaded, and they say which
        # instance of the source this wants.
        resolve_source_again(self, self.enrich_declaration, "source_assembly_name")
        await super().prepare_async(assembly)

        # What this object reports, settled here rather than while it is built:
        # a shape that comes out of the cache is never instantiated, and an
        # enrich has to answer the same either way (see 'adopt_source_config').
        source = self.ctx._get_assembly(self.source)
        if source is None:
            raise Exception(f"Failed to find the assembly to enrich: {self.source}")
        adopt_source_config(assembly, source, self.source)

    def instantiate(self, assembly):
        with pc_logging.Action("Enrich", assembly.project_name, f"{assembly.name}:{self.source_assembly_name}"):
            super().instantiate(assembly)
