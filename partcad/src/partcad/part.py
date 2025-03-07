#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import math
import typing

from .shape_ai import ShapeWithAi
from .sync_threads import threadpool_manager
from . import logging as pc_logging


class Part(ShapeWithAi):
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}, shape=None):
        super().__init__(project_name, config)

        self.kind = "part"
        self._wrapped = shape

        self.url = None
        if "url" in config:
            self.url = config["url"]

    async def get_shape(self, ctx):
        return await threadpool_manager.run_async(self.instantiate, self)

    async def get_mcftt(self, property: str):
        """Get the material, color, finish, texture or tolerance of the part."""

        store_data = self.get_store_data()

        if not (store_data.vendor and store_data.sku) and (
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
                pc_logging.warning(f"Part '{self.name}' has no '{property}'")

            return value

        if (
            "parameters" not in self.config
            or property not in self.config["parameters"]
            or "default" not in self.config["parameters"][property]
        ):
            return None
        return self.config["parameters"][property]["default"]
