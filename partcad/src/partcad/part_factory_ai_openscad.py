#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory_scad import PartFactoryScad
from .part_factory_feature_ai import PartFactoryFeatureAi
from . import logging as pc_logging


class PartFactoryAiScad(PartFactoryScad, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path determined by the parent class to enable "enrich"
        config["path"] = config["name"] + ".scad"

        with pc_logging.Action("InitAiScad", target_project.name, config["name"]):
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
