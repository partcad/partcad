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
from partcad.part_factory.part_factory_build123d import PartFactoryBuild123d
from partcad.part_factory.part_factory_feature_ai import PartFactoryFeatureAi
from partcad import logging as pc_logging


AI_BUILD123D = PartTypes.AI_BUILD123D

@register_factory(AI_BUILD123D.type)
class PartFactoryAiBuild123d(PartFactoryBuild123d, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path determined by the parent class to enable "enrich"
        config["path"] = config["name"] + f".{AI_BUILD123D.ext}"
        self.lang = self.LANG_PYTHON

        mode = "builder"
        if "mode" in config and config["mode"] == "algebra":
            mode = "algebra"

        with pc_logging.Action(f"Init{AI_BUILD123D.type.upper()}", target_project.name, config["name"]):
            PartFactoryFeatureAi.__init__(
                self,
                config,
                "build123d",
                "build123d script (in %s)" % mode,
                """Import all the required modules
(including 'math' and 'build123d' itself).
Do not export anything.
Use show_object() to display the part.
""",
            )
            PartFactoryBuild123d.__init__(
                self,
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )

            self.on_init_ai()
