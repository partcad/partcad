#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_provider import PluginRequestProvider


class ProviderRequestAvail(PluginRequestProvider):
    name: str
    vendor: str
    sku: str
    count_per_sku: int
    count: int

    item_in_sku: str = None

    def __init__(self, name: str, vendor: str, sku: str, count_per_sku: int, count: int, item_in_sku: str = None):
        super().__init__()
        self.item_in_sku = item_in_sku
        self.name = name
        self.vendor = vendor
        self.sku = sku
        self.count_per_sku = count_per_sku
        self.count = count

    def compose(self):
        return {
            "name": self.name,
            "vendor": self.vendor,
            "sku": self.sku,
            "count_per_sku": self.count_per_sku,
            "count": self.count,
            "item_in_sku": self.item_in_sku,
        }
