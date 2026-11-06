#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import re
import typing

from . import logging as pc_logging
from . import telemetry
from .plugin import Plugin
from .plugin_provider_data_cart import *
from .plugin_request_provider_caps import ProviderRequestCaps
from .plugin_request_provider_order import ProviderRequestOrder
from .plugin_request_provider_quote import ProviderRequestQuote


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


def declared_currency(config) -> typing.Optional[str]:
    """What a provider's configuration says its quotes are in: its 'currency' parameter, or the 'with' of an enrich.

    See "Providers" in the documentation: 'currency' is a parameter PartCAD
    reads itself.
    """
    config = config or {}
    currency = (config.get("parameters") or {}).get("currency")
    if isinstance(currency, dict):
        currency = currency.get("default")
    if not isinstance(currency, str) or not currency.strip():
        currency = (config.get("with") or {}).get("currency")
    return currency.strip().upper() if isinstance(currency, str) and currency.strip() else None


def with_currency(provider_name: str, config, result):
    """A quote as received from a provider, with the currency it is in always said.

    A price is a bare number, and a number without its currency is not a price:
    138 is a pair of armchairs in euros and something else in yen. So no quote
    is taken without one. It is the currency the quote says ('currency'), else
    the one the provider's configuration declares ('declared_currency'); a
    quote that says neither is taken to be in US dollars, which is what every
    quote was printed as before quotes said - and that is warned about, because
    it is a guess.
    """
    if not isinstance(result, dict) or result.get("price") is None:
        return result
    said = result.get("currency")
    if isinstance(said, str) and re.fullmatch(r"[A-Za-z]{3}", said.strip()):
        result["currency"] = said.strip().upper()
        return result
    declared = declared_currency(config)
    if declared:
        result["currency"] = declared
        return result
    pc_logging.warning(
        "%s quoted %s without saying in what currency: taken to be US dollars. A provider says it as "
        "'currency' in its answer, or as its 'currency' parameter" % (provider_name, result.get("price"))
    )
    result["currency"] = "USD"
    return result
