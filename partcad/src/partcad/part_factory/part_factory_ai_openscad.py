#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.part_factory.part_factory_scad import PartFactoryScad
from partcad.part_factory.part_factory_feature_ai import PartFactoryFeatureAi
from partcad import logging as pc_logging


AI_SCAD = PartTypes.AI_SCAD

@register_factory(AI_SCAD.type)
class PartFactoryAiScad(PartFactoryScad, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path determined by the parent class to enable "enrich"
        config["path"] = config["name"] + f".{AI_SCAD.ext}"

        with pc_logging.Action(f"Init{AI_SCAD.type.upper()}", target_project.name, config["name"]):
            PartFactoryFeatureAi.__init__(
                self,
                config,
                "scad",
                "OpenSCAD script",
                """Generate a complete functioning script, not just a code snippet.
There are no other non-standard modules available to import.
Define all necessary functions and constants.
Do not generate comments.
Do not export anything.
""",
            )
            PartFactoryScad.__init__(
                self,
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )

            self.on_init_ai()
