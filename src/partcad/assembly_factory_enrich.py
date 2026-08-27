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
    ENRICH_ONLY_PROPERTIES,
    INSTANCE_APPLIED_PROPERTIES,
    enriched_source_name,
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
            config = copy.copy(config)
            config["source"] = enriched_source_name(source_project, target_project, config)
            warn_about_ignored_properties(target_project, config, config["source"])
            # Fully qualified now, so the package it names must not be applied
            # to it a second time by the alias this hands the work to.
            config.pop("package", None)
            config.pop("project", None)
            super().__init__(ctx, source_project, target_project, config)

    def instantiate(self, assembly):
        with pc_logging.Action("Enrich", assembly.project_name, f"{assembly.name}:{self.source_assembly_name}"):
            source = self.ctx._get_assembly(self.source)
            if source is None:
                raise Exception(f"Failed to find the assembly to enrich: {self.source}")

            # The parameters this enrich resolved to are reported by it; what it
            # declares itself stays its own. See 'PartFactoryEnrich'.
            enrich_config = assembly.config
            assembly.config = {
                key: value for key, value in source.get_final_config().items() if key not in INSTANCE_APPLIED_PROPERTIES
            }
            for prop_to_copy in enrich_config:
                if prop_to_copy in ENRICH_ONLY_PROPERTIES:
                    continue
                assembly.config[prop_to_copy] = enrich_config[prop_to_copy]
            assembly.config["source"] = self.source
            assembly.config["orig_name"] = assembly.name
            assembly.config["name"] = enrich_config["name"]

            super().instantiate(assembly)
