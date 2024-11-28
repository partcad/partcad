#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from .provider_request import ProviderRequest


class ProviderRequestCaps(ProviderRequest):
    def __init__(self):
        pass

    def compose(self):
        # This request has no parameters
        return {}
