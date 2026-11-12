#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration
from .part_config_manufacturing import PartConfigManufacturing, implied_type
from .shape_config import ShapeConfiguration


class PartConfiguration(Configuration, ShapeConfiguration):
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name, user_config=None):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        # A printed part that names its design and no geometry of its own is
        # that design, printed: drawn, placed and exported as its visual (see
        # 'part_config_manufacturing.implied_type').
        implied = implied_type(config)
        if implied:
            config.update(implied)

        config = Configuration.normalize(name, config, object_name, user_config)
        return ShapeConfiguration.normalize(name, config)

    @staticmethod
    def get_manufacturing_data(part) -> PartConfigManufacturing:
        final_config = part.get_final_config()
        return PartConfigManufacturing(final_config)
