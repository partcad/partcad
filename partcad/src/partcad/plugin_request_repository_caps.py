#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-31
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_repository import PluginRequestRepository


class PluginRequestRepositoryCaps(PluginRequestRepository):
    result: object = None

    def __init__(self):
        super().__init__()

    def compose(self):
        composed = {
            "name": self.name,
        }
        if not self.result is None:
            composed["result"] = self.result
        return composed
