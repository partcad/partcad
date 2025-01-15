#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-08-09
#
# Licensed under Apache License, Version 2.0.
#


class NeedsUpdateException(Exception):
    pass

class EmptyShapesError(Exception):
    """Exception raised when no shapes are found for rendering."""

    def __init__(self, message="No shapes found to render. Please specify valid sketches, parts, or assemblies."):
        self.message = message
        super().__init__(self.message)
