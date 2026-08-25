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
        # A capabilities request carries no name (it is about the repository as
        # a whole, not a single object).
        composed = {}
        if self.result is not None:
            composed["result"] = self.result
        return composed
