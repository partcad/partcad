#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Moved to 'partcad.qual.registry'; this name is the same module, kept for what imports it from here."""

import sys

from ..qual import registry as _moved

sys.modules[__name__] = _moved
