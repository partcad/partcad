#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import tempfile

from .plugin_request_provider_caps import ProviderRequestCaps
from .plugin_request_provider_order import ProviderRequestOrder
from .plugin_request_provider_quote import ProviderRequestQuote
from .plugin_factory_provider import PluginFactoryProvider
from .plugin_provider_data_cart import *
from .part import Part
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class PluginFactoryProviderManufacturer(PluginFactoryProvider):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitManuf", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )
            # Complement the config object here if necessary

            self._create(config)

    def _create(self, config):
        super()._create(config)
        self.plugin.is_part_available = self.is_part_available
        self.plugin.load = self.load
        self.plugin.query_caps = self.query_caps
        self.plugin.query_quote = self.query_quote
        self.plugin.query_order = self.query_order

    async def is_part_available(self, cart_item: ProviderCartItem):
        # TODO(clairbee): add vendor/SKU-based availability check
        caps = await self.plugin.get_caps()
        if cart_item.material:
            if not cart_item.material in caps["materials"]:
                return False
            if cart_item.color:
                # TODO(clairbee): implement color mapping as a function in
                #                 the corresponding module
                #                 (resolve cart_item.color as a color object)
                if cart_item.color not in list(
                    map(
                        lambda c: c["name"],
                        caps["materials"][cart_item.material]["colors"],
                    )
                ):
                    return False
            if cart_item.finish:
                # TODO(clairbee): implement finish mapping as a function in
                #                 the corresponding module
                #                 (resolve cart_item.finish as a finish object)
                if cart_item.finish not in list(
                    map(
                        lambda f: f["name"],
                        caps["materials"][cart_item.material]["finishes"],
                    )
                ):
                    pc_logging.debug("Provider %s does not support finish %s" % (self.name, cart_item.finish))
                    pc_logging.debug("Supported finishes: %s" % caps["materials"][cart_item.material]["finishes"])
                    return False
        return True

    async def load(self, cart_item: ProviderCartItem):
        """Load the CAD binary into the cart item based on the provider capabilities."""
        caps = await self.plugin.get_caps()
        # TODO(clairbee): Make the below more generic
        if "formats" in caps and "step" in caps["formats"]:
            part: Part = self.ctx.get_part(cart_item.name)
            filepath = tempfile.mktemp(".step")
            await part.render_async(self.ctx, format_name="step", filepath=filepath)
            with open(filepath, "rb") as f:
                step = f.read()
            cart_item.add_binary("step", step)
        else:
            # TODO(clairbee): add support for other formats
            pc_logging.error(f"Provider {self.plugin.name} does not support STEP format.")

    async def query_caps(self, request: ProviderRequestCaps):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "caps", request.compose()
        # )
        return await self.query_script(self.plugin, "caps", request.compose())

    async def query_quote(self, request: ProviderRequestQuote):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "quote", request.compose(),
        # )
        return await self.query_script(self.plugin, "quote", request.compose())

    async def query_order(self, request: ProviderRequestOrder):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "order", request.compose(),
        # )
        return await self.query_script(self.plugin, "order", request.compose())
