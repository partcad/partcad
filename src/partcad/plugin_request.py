#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-31
#
# Licensed under Apache License, Version 2.0.
#

import abc


class PluginRequest(abc.ABC):
    def __init__(self):
        # This class is a base class for all plugin requests
        # It should not be instantiated directly
        # Instead, use one of the child classes
        self.result = None

    def compose(self) -> dict:
        # This method must be implemented in the child class
        raise NotImplementedError()

    def set_result(self, result: object):
        self.result = result

    def __repr__(self):
        return str(self.compose())
