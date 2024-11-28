#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from .provider_data_cart import *
from .provider_request import ProviderRequest


class ProviderRequestQuote(ProviderRequest):
    cart: ProviderCart = None
    result: object = None

    def __init__(self, cart: ProviderCart = ProviderCart()):
        self.cart = cart
        self.result = None

    def set_result(self, result: object):
        self.result = result

    def compose(self):
        composed = {
            "cart": self.cart.compose(),
        }
        if not self.result is None:
            composed["result"] = self.result
        return composed

    def __repr__(self):
        return str(self.compose())
