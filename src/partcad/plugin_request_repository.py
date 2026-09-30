#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request import PluginRequest


class PluginRequestRepository(PluginRequest):
    """
    PluginRequestRepository is a base class for all repository-related plugin requests.
    It inherits from PluginRequest and provides a structure for handling repository-related operations.
    """

    def __init__(self):
        super().__init__()
