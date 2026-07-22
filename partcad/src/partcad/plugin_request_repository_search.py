#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_repository import PluginRequestRepository


class PluginRequestRepositorySearch(PluginRequestRepository):
    keywords: list[str]
    result: object = None

    def __init__(self, keywords: list[str]):
        super().__init__()
        self.keywords = keywords

    def compose(self):
        composed = {
            "keywords": self.keywords,
        }
        if not self.result is None:
            composed["result"] = self.result
        return composed
