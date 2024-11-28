#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import random
import string


class ShapeConfiguration:
    def __init__(self, config):
        self.config = config
        if "name" in config:
            self.name = config["name"]
        else:
            name = "part" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            self.name = name
            self.config["name"] = name

    @staticmethod
    def normalize(name, config):
        # Handle the case of the part being declared in the config
        # but not defined (a one liner like "part_name:").
        # TODO(clairbee): Revisit whether it's a bug or a feature
        #                 that this code allows to load undeclared scripts
        if config is None:
            config = {}

        # Instead of passing the name as a parameter,
        # enrich the configuration object
        # TODO(clairbee): reconsider passing the name as a parameter
        config["name"] = name
        config["orig_name"] = name

        return config
