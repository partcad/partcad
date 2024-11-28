#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import tempfile

from .provider_request_avail import ProviderRequestAvail
from .provider_request_order import ProviderRequestOrder
from .provider_request_quote import ProviderRequestQuote
from .provider_factory_python import ProviderFactoryPython
from .provider_data_cart import *
from . import logging as pc_logging

# from . import sync_threads as pc_thread


class ProviderFactoryStore(ProviderFactoryPython):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action(
            "InitStore", target_project.name, config["name"]
        ):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )
            # Complement the config object here if necessary

            self._create(config)
            self.provider.is_part_available = self.is_part_available
            self.provider.load = self.load
            self.provider.query_quote = self.query_quote
            self.provider.query_order = self.query_order

    async def is_part_available(self, cart_item: ProviderCartItem):
        request = ProviderRequestAvail(
            self.name,
            cart_item.vendor,
            cart_item.sku,
            cart_item.count_per_sku,
            cart_item.count,
        )
        availability = await self.query_script(
            self.provider,
            "avail",
            request.compose(),
        )
        return (
            availability["available"]
            if availability and "available" in availability
            else False
        )

    async def load(self, cart_item: ProviderCartItem):
        """No-op. No CAD binary to be loded."""
        pass

    async def query_quote(self, request: ProviderRequestQuote):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.provider, "quote", request.compose(),
        # )
        return await self.query_script(
            self.provider, "quote", request.compose()
        )

    async def query_order(self, request: ProviderRequestOrder):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.provider, "order", request.compose(),
        # )
        return await self.query_script(
            self.provider, "order", request.compose()
        )
