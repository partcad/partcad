#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#


class ProviderRequest:
    def compose(self) -> dict:
        # This method must be implemented in the child class
        raise NotImplementedError()
