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

class PartFactoryBrepError(Exception):
    """Custom exception for PartFactoryBrep errors."""
    pass

class BREPProcessingError(Exception):
    """Custom exception for BREP processing errors."""
    pass
