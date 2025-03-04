from .user_config import user_config


class Configuration:
    def __init__(self, name, config) -> None:
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
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
                elif isinstance(param_value, dict) and "type" not in param_value:
                    param_value["type"] = "float"

        # Override parameters with user configuration
        config_parameters = user_config.parameter_config.to_dict()
        if object_name in config_parameters and "parameters" in config:
            parameter_config = config_parameters[object_name]
            for param_name in parameter_config:
                config["parameters"][param_name]["default"] = parameter_config[param_name]
        return config
