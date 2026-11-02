#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import assembly_factory_alias as afa
from . import logging as pc_logging
from . import telemetry
from .enrich import (
    adopt_source_config,
    enriched_source_name,
    resolve_source_again,
    warn_about_ignored_properties,
)


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

            # Joined by its source's ports, unless it maps its own (see
            # 'prepare_async' below): asked for here, they need no preparation
            # of this object to be waited for.
            if not self.enrich_declaration.get("map"):
                self.assembly.find_ports_source = self.find_ports_source

    def find_ports_source(self):
        """The assembly whose ports this one is joined by: the instance it enriches, or None if not found.

        What 'shape_ports.prepare_async' asks, rather than waiting for this
        object to be prepared - which is to wait for whatever else that
        preparation waits for, on whichever thread it is under way. The answer
        is the instance the preparation resolves to as well, short of a
        parameter override of the user's arriving in between, which the
        preparation then settles (see 'resolve_source_again').
        """
        source = self.get_source_object(self.source)
        if source is not None and getattr(source, "with_ports", None) is not None:
            self.assembly.with_ports = source.with_ports
            self.assembly.ports_source = source
        return source

    async def prepare_async(self, assembly) -> None:
        # Before anything is resolved: the user's own parameter overrides may
        # have arrived after this package was loaded, and they say which
        # instance of the source this wants.
        resolve_source_again(self, self.enrich_declaration, "source_assembly_name")
        await super().prepare_async(assembly)

        # What this object reports, settled here rather than while it is built:
        # a shape that comes out of the cache is never instantiated, and an
        # enrich has to answer the same either way (see 'adopt_source_config').
        source = self.get_source_object(self.source)
        if source is None:
            raise Exception(f"Failed to find the assembly to enrich: {self.source}")
        adopt_source_config(assembly, source, self.source)
        # And the ports it is joined by are its source's. An assembly's own
        # come from its 'map:', worked out from where its children are, and the
        # instance this enriches is where those children are: an assembly in a
        # colour of its own - a LEGO wheel, a battery box - is joined by exactly
        # the ports the one it is a variant of is.
        #
        # Only pointed at here, not worked out: that walks the source, which
        # builds it, and a preparation is something every reader of this
        # object's cache key waits for - a minute of building inside it is a
        # minute they wait, and longer than they may. 'shape_ports.prepare_async'
        # resolves them, on the source, for whoever asks for the ports.
        #
        # One that declares a 'map:' of its own is joined by what that names,
        # which is worked out on this object like any other assembly's.
        if not self.enrich_declaration.get("map") and getattr(source, "with_ports", None) is not None:
            assembly.with_ports = source.with_ports
            assembly.ports_source = source

    def instantiate(self, assembly):
        with pc_logging.Action("Enrich", assembly.project_name, f"{assembly.name}:{self.source_assembly_name}"):
            super().instantiate(assembly)
