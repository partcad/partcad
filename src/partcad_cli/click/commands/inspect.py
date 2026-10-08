#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Deprecated: `pc ide view`, under the name it had before there was a `pc ide`."""

from .ide import deprecated_alias
from .ide.view import cli as _view

cli = deprecated_alias(_view, "pc inspect", "pc ide view")
