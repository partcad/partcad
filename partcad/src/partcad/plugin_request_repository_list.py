#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_repository import PluginRequestRepository


class PluginRequestRepositoryList(PluginRequestRepository):
    sub_packages: list[str]
    result: object = None

    def __init__(self, sub_packages: list[str] = None):
        super().__init__()
        self.sub_packages = sub_packages if sub_packages is not None else []

    def compose(self):
        composed = {}
        if not self.result is None:
            composed["result"] = self.result
        return composed
