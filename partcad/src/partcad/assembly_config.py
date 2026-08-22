#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .assembly_config_manufacturing import METHOD_ASSY as ASSEMBLY_METHOD_ASSY
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

        # An assembly defined by an ASSY file carries its own instructions for
        # putting itself together, which is what the "assy" manufacturing method
        # is, so it does not have to say so. Anything the file does say wins.
        if config.get("type", None) == "assy":
            manufacturing = config.setdefault("manufacturing", {})
            if isinstance(manufacturing, dict):
                manufacturing.setdefault("method", ASSEMBLY_METHOD_ASSY)

        config = Configuration.normalize(name, config, object_name)
        return ShapeConfiguration.normalize(name, config)

    @staticmethod
    def get_manufacturing_data(assembly) -> AssemblyConfigManufacturing:
        final_config = assembly.get_final_config()
        return AssemblyConfigManufacturing(final_config)
