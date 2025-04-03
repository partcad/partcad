#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_provider_data_cart import *
from .plugin_request_provider import PluginRequestProvider


class ProviderRequestQuote(PluginRequestProvider):
    cart: ProviderCart = None
    result: object = None

    def __init__(self, cart: ProviderCart = None):
        super().__init__()
        if cart is None:
            self.cart = ProviderCart()
        else:
            self.cart = cart

    def compose(self):
        composed = {
            "cart": self.cart.compose(),
        }
        if not self.result is None:
            composed["result"] = self.result
        return composed
