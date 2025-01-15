#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .shape_config import ShapeConfiguration
from .part_config_manufacturing import PartConfigManufacturing


class PartConfiguration(ShapeConfiguration):
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        if "parameters" in config:
            for param_name, param_value in config["parameters"].items():
                # Expand short formats
                if isinstance(param_value, str):
                    config["parameters"][param_name] = {
                        "type": "string",
                        "default": param_value,
                    }
                elif isinstance(param_value, bool):
                    config["parameters"][param_name] = {
                        "type": "bool",
                        "default": param_value,
                    }
                elif isinstance(param_value, float):
                    config["parameters"][param_name] = {
                        "type": "float",
                        "default": param_value,
                    }
                elif isinstance(param_value, int):
                    config["parameters"][param_name] = {
                        "type": "int",
                        "default": param_value,
                    }
                elif isinstance(param_value, list):
                    config["parameters"][param_name] = {
                        "type": "array",
                        "default": param_value,
                    }
                # All params are float unless another type is explicitly speciifed
                elif isinstance(param_value, dict) and not "type" in param_value:
                    param_value["type"] = "float"

        return ShapeConfiguration.normalize(name, config)

    @staticmethod
    def get_manufacturing_data(part) -> PartConfigManufacturing:
        final_config = part.get_final_config()
        return PartConfigManufacturing(final_config)
