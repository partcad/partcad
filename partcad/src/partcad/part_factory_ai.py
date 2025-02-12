from partcad.part_factory_build123d import PartFactoryBuild123d
from partcad.part_factory_cadquery import PartFactoryCadquery
from .part_factory_scad import PartFactoryScad
from .part_factory_feature_ai import PartFactoryFeatureAi
from . import logging as pc_logging


class PartFactoryAi(PartFactoryFeatureAi):
    """Factory for AI-generated parts, dynamically selecting modeling type."""

    def __init__(self, ctx, source_project, target_project, config):
        # Set the correct file extension based on the type
        file_extensions = {
            "cadquery": ".py",
            "build123d": ".py",
            "openscad": ".scad",
        }

        part_type = config["type"]
        if part_type not in file_extensions:
            raise Exception(f"Invalid AI-generated part type: {part_type}")

        config["path"] = config["name"] + file_extensions[part_type]
        self.lang = self.LANG_PYTHON if part_type in ["cadquery", "build123d"] else None

        # Set logging action tags per type
        action_tags = {
            "cadquery": "InitAiCq",
            "build123d": "InitAiB3d",
            "openscad": "InitAiScad",
        }

        with pc_logging.Action(action_tags[part_type], target_project.name, config["name"]):
            # AI script descriptions and specific rules
            script_description = {
                "cadquery": "CadQuery 2.0 script",
                "build123d": "build123d script",
                "openscad": "OpenSCAD script",
            }

            ai_prompt_suffix = {
                "cadquery": """Generate a complete functioning script, not just a code snippet.
Import all required modules (including 'math' and 'cadquery').
Do not use tetrahedron, hexahedron.
Do not generate comments.
Do not export anything.
Use "show_object()" to display the part.
""",
                "build123d": """Import all required modules (including 'math' and 'build123d').
Do not export anything.
Use show_object() to display the part.
""",
                "openscad": """Generate a complete functioning script, not just a code snippet.
No other non-standard modules are available.
Define all necessary functions and constants.
Do not generate comments.
Do not export anything.
""",
            }

            if part_type == "build123d":
                mode = config.get("mode", "builder")
                if mode not in ["builder", "algebra"]:
                    pc_logging.warning(
                        f"Invalid mode '{mode}' for build123d. Defaulting to 'builder'."
                    )
                    mode = "builder"
                script_description["build123d"] = f"build123d script (in {mode})"

            PartFactoryFeatureAi.__init__(
                self,
                config,
                part_type,
                script_description[part_type],
                ai_prompt_suffix[part_type],
            )

            # Call the standard factory constructor for the selected type
            factory_mapping = {
                "cadquery": PartFactoryCadquery,
                "build123d": PartFactoryBuild123d,
                "openscad": PartFactoryScad,
            }

            factory_mapping[part_type](
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )

            self.on_init_ai()
