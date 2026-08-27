#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import copy
import typing

from . import sketch_factory_alias as sfa
from . import logging as pc_logging
from .enrich import adopt_source_config, enriched_source_name, warn_about_ignored_properties
from . import telemetry


@telemetry.instrument()
class SketchFactoryEnrich(sfa.SketchFactoryAlias):
    """An alias to a parameterized instance of the sketch it enriches.

    See 'PartFactoryEnrich' for what that means and why it is the whole of what
    an enrich has to do.
    """

    source_sketch_name: str
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

            config = copy.copy(config)
            config["source"] = source
            # Fully qualified now, so the package it names must not be applied
            # to it a second time by the alias this hands the work to.
            config.pop("package", None)
            config.pop("project", None)
            super().__init__(ctx, source_project, target_project, config)

    async def prepare_async(self, sketch) -> None:
        await super().prepare_async(sketch)

        # What this object reports, settled here rather than while it is built:
        # a shape that comes out of the cache is never instantiated, and an
        # enrich has to answer the same either way (see 'adopt_source_config').
        source = self.ctx._get_sketch(self.source)
        if source is None:
            raise Exception(f"Failed to find the sketch to enrich: {self.source}")
        adopt_source_config(sketch, source, self.source)

    async def instantiate(self, sketch):
        with pc_logging.Action("Enrich", sketch.project_name, f"{sketch.name}:{self.source_sketch_name}"):
            return await super().instantiate(sketch)
