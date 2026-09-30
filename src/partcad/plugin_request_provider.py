#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-31
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request import PluginRequest


class PluginRequestProvider(PluginRequest):
    """
    PluginRequestProvider is a base class for all provider-related plugin requests.
    It inherits from PluginRequest and provides a structure for handling provider-related operations.
    """

    def __init__(self):
        super().__init__()
