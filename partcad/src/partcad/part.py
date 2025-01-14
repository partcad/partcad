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
from . import sync_threads as pc_thread
from . import logging as pc_logging


class Part(ShapeWithAi):
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    count: int = None

    def __init__(self, config: object = {}, shape=None):
        super().__init__(config)

        self.kind = "parts"
        self.shape = shape

        self.url = None
        if "url" in config:
            self.url = config["url"]
        self.count = 0

    async def get_shape(self):
        async with self.locked():
            if self.shape is None:
                self.shape = await pc_thread.run_async(self.instantiate, self)
            return self.shape

    def ref_inc(self):
        # TODO(clairbee): add a thread lock here
        self.count += 1

    def clone(self):
        cloned = Part(self.name, self.config, self.shape)
        cloned.count = self.count
        return cloned

    async def get_mcftt(self, property: str):
        """Get the material, color, finish, texture or tolerance of the part."""

        store_data = self.get_store_data()

        if (not store_data.vendor or not store_data.sku) and (
            "parameters" not in self.config or property not in self.config["parameters"]
        ):
            shape = await self.get_shape()
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

    def _render_txt_real(self, file):
        file.write(self.name + ": " + self.count + "\n")

    def _render_markdown_real(self, file):
        name = self.name
        if not self.desc is None:
            name = self.desc
        store_data = self.get_store_data()
        vendor = store_data.vendor if store_data.vendor else ""
        sku = store_data.sku if store_data.sku else ""
        if self.url is None:
            label = name
        else:
            label = f"[{name}]({self.url})"
            sku = f"[{sku}]({self.url})" if sku else ""
        count = str(math.ceil(self.count / store_data.count_per_sku))
        img_url = self._get_svg_url()

        file.write(
            "| "
            + label
            + " | "
            + count
            + " |"
            + vendor
            + " |"
            + sku
            + " |"
            + " !["
            + name
            + "]("
            + img_url
            + ")"
            + " |\n"
        )
