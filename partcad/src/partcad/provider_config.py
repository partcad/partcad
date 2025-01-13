#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#


class ProviderConfiguration:
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config):
        if config is None:
            config = {}

        # Instead of passing the name as a parameter,
        # enrich the configuration object
        # TODO(clairbee): reconsider passing the name as a parameter
        config["name"] = name
        config["orig_name"] = name

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
                # All params are float unless another type is explicitly specified
                elif isinstance(param_value, dict) and not "type" in param_value:
                    param_value["type"] = "float"

        return config
