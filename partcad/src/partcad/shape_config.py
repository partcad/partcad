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

from partcad.shape_config_store import ShapeConfigStore
from . import logging as pc_logging


class ShapeConfiguration:
    is_manufacturable: bool = False

    def __init__(self, config: dict) -> None:
        self.config = config

        if "name" in config:
            self.name = config["name"]
        else:
            name = "part" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            self.name = name
            self.config["name"] = name

        self.is_manufacturable = bool(config.get("manufacturable", True))

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

    def get_final_config(self) -> dict:
        """Return the final configuration (once all "alias" and "enrich" directives are resolved)."""
        return self.config

    def get_store_data(self) -> ShapeConfigStore:
        final_config = self.get_final_config()
        return ShapeConfigStore(final_config)

    async def get_mcftt(self, property: str):
        """Get the material, color, finish, texture or tolerance of the object."""

        store_data = self.get_store_data()

        if not store_data.is_purchasable and (
            "parameters" not in self.config or property not in self.config["parameters"]
        ):
            # shape = await self.get_wrapped()
            # TODO(clairbee): derive the property from the model

            if property == "finish":
                # By default, the finish is set to "none"
                value = "none"
            else:
                # By default, the parameter is not set
                value = None

            if value:
                if "parameters" not in self.config:
                    self.config["parameters"] = {}
                self.config["parameters"][property] = {
                    "type": "string",
                    "enum": [value],
                    "default": value,
                }
            else:
                kind = getattr(self, "kind", "object").capitalize()
                pc_logging.warning(f"{kind} '{self.name}' has no '{property}'")

            return value

        if (
            "parameters" not in self.config
            or property not in self.config["parameters"]
            or "default" not in self.config["parameters"][property]
        ):
            return None
        return self.config["parameters"][property]["default"]
