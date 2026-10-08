#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-16
#
# Licensed under Apache License, Version 2.0.
#
"""Where `RuntimeJsonRpcClient` used to live; it is `partcad_utils.json_rpc_client` now.

Moved so that a client -- `pc ide open` -- can talk to a container without importing
the core. Re-exported here for everything that imported it from here.
"""

from partcad_utils.json_rpc_client import RuntimeJsonRpcClient

__all__ = ["RuntimeJsonRpcClient"]
