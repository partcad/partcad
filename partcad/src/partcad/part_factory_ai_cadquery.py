#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory_cadquery import PartFactoryCadquery
from .part_factory_feature_ai import PartFactoryFeatureAi
from . import logging as pc_logging


class PartFactoryAiCadquery(PartFactoryCadquery, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path determined by the parent class to enable "enrich"
        config["path"] = config["name"] + ".py"
        self.lang = self.LANG_PYTHON

        with pc_logging.Action("InitAiCq", target_project.name, config["name"]):
            PartFactoryFeatureAi.__init__(
                self,
                config,
                "cadquery",
                "CadQuery 2.0 script",
                """Generate a complete functioning script, not just a code snippet.
Import all the required modules (including 'math' and 'cadquery' itself).
Do not use methods: tetrahedron, hexahedron.
Do not generate comments.
Do not export anything.
Use "show_object()" to display the part.
""",
            )
            PartFactoryCadquery.__init__(
                self,
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )

            self.on_init_ai()
