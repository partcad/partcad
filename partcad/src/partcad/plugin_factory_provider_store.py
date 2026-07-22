#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_provider_avail import ProviderRequestAvail
from .plugin_request_provider_order import ProviderRequestOrder
from .plugin_request_provider_quote import ProviderRequestQuote
from .plugin_factory_provider import PluginFactoryProvider
from .plugin_provider_data_cart import *
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class PluginFactoryProviderStore(PluginFactoryProvider):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitStore", target_project.name, config["name"]):
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
        self.plugin.query_quote = self.query_quote
        self.plugin.query_order = self.query_order

    async def is_part_available(self, cart_item: ProviderCartItem):
        pc_logging.debug("Checking availability of %s" % cart_item)
        request = ProviderRequestAvail(
            self.name,
            cart_item.vendor,
            cart_item.sku,
            cart_item.count_per_sku,
            cart_item.count,
        )
        availability = await self.query_script(
            self.plugin,
            "avail",
            request.compose(),
        )
        return availability["available"] if availability and "available" in availability else False

    async def load(self, cart_item: ProviderCartItem):
        """No-op. No CAD binary to be loaded."""
        pass

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
