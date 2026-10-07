#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Deprecated: `pc ide open`, under the name it had before there was a `pc ide`."""

from .ide import deprecated_alias
from .ide.open import cli as _open

cli = deprecated_alias(_open, "pc open", "pc ide open")
