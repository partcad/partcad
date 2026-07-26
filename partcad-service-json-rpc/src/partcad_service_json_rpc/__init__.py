#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""JSON-RPC service exposing PartCAD functionality.

The service mirrors ``partcad-cli`` actions over a JSON-RPC 2.0 interface. It
serves over stdin/stdout by default and, optionally, over HTTP. See
``partcad_service_json_rpc.__main__`` for the executable entry point.
"""

__version__ = "0.7.146"
