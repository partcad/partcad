#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory_build123d import PartFactoryBuild123d
from .part_factory_feature_ai import PartFactoryFeatureAi
from . import logging as pc_logging


class PartFactoryAiBuild123d(PartFactoryBuild123d, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path determined by the parent class to enable "enrich"
        config["path"] = config["name"] + ".py"
        self.lang = self.LANG_PYTHON

        mode = "builder"
        if "mode" in config and config["mode"] == "algebra":
            mode = "algebra"

        with pc_logging.Action("InitAiB3d", target_project.name, config["name"]):
            PartFactoryBuild123d.__init__(
                self,
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )
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

            self.on_init_ai()
