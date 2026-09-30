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


class ProviderRequestCaps(PluginRequestProvider):
    def __init__(self):
        super().__init__()

    def compose(self):
        # This request has no parameters
        return {}
