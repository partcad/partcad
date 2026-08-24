#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Shared lightweight utilities for the PartCAD ecosystem.

This package holds the pieces that both the heavy ``partcad`` core and the thin
clients (``partcad-cli``, ``partcad-service-json-rpc``, the VS Code extension)
need, without any CAD-kernel dependency. Importing a module here (e.g.
``partcad_utils.logging_ansi_terminal``) is cheap, which is what lets the CLI
render streamed daemon output without paying the ~1.6s cost of importing
``partcad`` on every command.

``partcad`` aliases these modules back under its own namespace (``partcad.logging``
is ``partcad_utils.logging``), so existing imports keep working unchanged.
"""

__version__ = "0.7.193"
