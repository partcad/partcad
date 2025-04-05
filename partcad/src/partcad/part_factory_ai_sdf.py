from .part_factory_sdf import PartFactorySdf
from .part_factory_feature_ai import PartFactoryFeatureAi
from . import logging as pc_logging


class PartFactoryAiSdf(PartFactorySdf, PartFactoryFeatureAi):
    def __init__(self, ctx, source_project, target_project, config):
        # Override the path to enable "enrich"
        config["path"] = config["name"] + ".py"
        self.lang = self.LANG_PYTHON

        with pc_logging.Action("InitAiSdf", target_project.name, config["name"]):
            PartFactoryFeatureAi.__init__(
                self,
                config,
                "sdf",
                "SDF script",
                """Generate a complete functioning SDF script.
Import all required modules (including 'math' and 'sdf').
Do not generate comments.
Do not export anything.
Use show_object() to display the part.
""",
            )
            PartFactorySdf.__init__(
                self,
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )

            self.on_init_ai()
