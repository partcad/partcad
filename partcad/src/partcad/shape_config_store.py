#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#


class ShapeConfigStore:
    vendor: str | None
    sku: str | None
    count_per_sku: int

    def __init__(self, final_config):
        self.vendor = final_config.get("vendor", None)
        self.sku = final_config.get("sku", None)
        self.count_per_sku = final_config.get("count_per_sku", 1)

    def __str__(self) -> str:
        return f"ShapeConfigStore(vendor={self.vendor}, sku={self.sku}, count_per_sku={self.count_per_sku})"
