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

    @property
    def is_purchasable(self) -> bool:
        """Whether the object can be bought off the shelf.

        Both the vendor and the SKU are needed to order anything: the SKU alone
        does not say from whom, and the vendor alone does not say what.
        """
        return bool(self.vendor and self.sku)

    def __str__(self) -> str:
        return f"ShapeConfigStore(vendor={self.vendor}, sku={self.sku}, count_per_sku={self.count_per_sku})"
