#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .plugin_request_provider_caps import ProviderRequestCaps
from .plugin_request_provider_order import ProviderRequestOrder
from .plugin_request_provider_quote import ProviderRequestQuote
from .plugin_provider_data_cart import *
from .plugin import Plugin
from . import telemetry


@telemetry.instrument()
class Provider(Plugin):
    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__(name, config, target_project_name)

    def is_qos_available(self, qos: str) -> bool:
        # TODO(clairbee): use the config to determine if the QoS is available
        return True

    async def get_caps(self) -> dict[str, typing.Any]:
        if not self.caps:
            self.caps = await self.query_caps(ProviderRequestCaps())
        return self.caps

    async def is_part_available(self, cart_item: ProviderCartItem):
        raise NotImplementedError()

    async def load(self, cart_item: ProviderCartItem):
        raise NotImplementedError()

    async def query_caps(self, request: ProviderRequestCaps):
        raise NotImplementedError()

    async def query_quote(self, request: ProviderRequestQuote):
        raise NotImplementedError()

    async def query_order(self, request: ProviderRequestOrder):
        raise NotImplementedError()
