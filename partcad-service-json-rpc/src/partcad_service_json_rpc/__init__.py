#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""JSON-RPC service exposing PartCAD functionality.

The service mirrors ``partcad-cli`` actions over a JSON-RPC 2.0 interface. By
default it runs a per-workspace background daemon (a warm context served over a
Unix socket, or a named pipe on Windows); ``--stdio`` and ``--http`` select the
foreground transports instead. See ``partcad_service_json_rpc.__main__`` for the
executable entry point.
"""

__version__ = "0.7.153"
