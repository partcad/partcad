#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_repository import PluginRequestRepository


class PluginRequestRepositoryGet(PluginRequestRepository):
    name: str
    result: object = None

    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def compose(self):
        composed = {
            "name": self.name,
        }
        if not self.result is None:
            composed["result"] = self.result
