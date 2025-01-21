#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from async_lru import alru_cache
import typing

from .provider_request_caps import ProviderRequestCaps
from .provider_request_order import ProviderRequestOrder
from .provider_request_quote import ProviderRequestQuote
from .provider_data_cart import *
from . import logging as pc_logging
from .sentry import instrument


@instrument()
class Provider:
    name: str
    config: dict[str, typing.Any] = None
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]
    caps: dict[str, typing.Any] = None

    def __init__(self, name: str, config: dict[str, typing.Any] = {}):
        super().__init__()
        self.name = name
        self.config = config
        self.errors = []
        self.url = config.get("url", None)

        self.get_caps = alru_cache(maxsize=1, typed=True)(self.get_caps)

    def error(self, msg: str):
        mute = self.config.get("mute", False)
        if mute:
            self.errors.append(msg)
        else:
            pc_logging.error(msg)

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
