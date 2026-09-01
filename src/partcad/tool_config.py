#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration


class ToolConfiguration:
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if config is None:
            config = {}

        if isinstance(config, str):
            # The short form: the value is the part that stands for the tool.
            # A tool with nothing but a likeness is a perfectly ordinary thing
            # to declare - a finger has no torque rating - so it gets a spelling
            # of its own rather than a one-key mapping.
            config = {"visual": config}

        # A tool's 'type' is its category, and the category is where the
        # declaration sits: 'Project._tool_configs' has already copied the
        # sub-section name in. Mirroring it into 'type' is what lets the generic
        # object plumbing dispatch on it ('factory.instantiate'), which is the
        # whole reason the three categories are three classes.
        config["type"] = config.get("category", None)

        return Configuration.normalize(name, config, object_name)
