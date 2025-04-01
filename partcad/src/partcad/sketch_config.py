#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration
from .shape_config import ShapeConfiguration


class SketchConfiguration(Configuration, ShapeConfiguration):
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        config = Configuration.normalize(name, config, object_name)
        return ShapeConfiguration.normalize(name, config)
