#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration


class MaterialConfiguration:
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if config is None:
            config = {}

        if isinstance(config, str):
            # The short form: the value is the full name of the substance.
            # 'pla: Polylactic Acid' is the whole of what a small catalogue
            # wants to say, and making it write a mapping to say it would be
            # asking for ceremony rather than information.
            config = {"full": config}

        # Unlike every other object kind, a material has no 'type': there is
        # one way to be a material, and nothing constructs it. That is why
        # there is no factory here and why 'Project.init_material_by_config'
        # builds the object directly, the way interfaces are built.

        return Configuration.normalize(name, config, object_name)
