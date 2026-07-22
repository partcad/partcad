#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .assembly_config_manufacturing import AssemblyConfigManufacturing
from .config import Configuration
from .shape_config import ShapeConfiguration


class AssemblyConfiguration(Configuration, ShapeConfiguration):
    def __init__(self, name, config=None):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        config = Configuration.normalize(name, config, object_name)
        return ShapeConfiguration.normalize(name, config)

    @staticmethod
    def get_manufacturing_data(assembly) -> AssemblyConfigManufacturing:
        final_config = assembly.get_final_config()
        return AssemblyConfigManufacturing(final_config)
