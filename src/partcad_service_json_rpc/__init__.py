#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""JSON-RPC service exposing PartCAD functionality.

The service mirrors ``partcad-cli`` actions over a JSON-RPC 2.0 interface. By
default it runs a per-workspace background daemon (a Unix socket, or a named
pipe on Windows); ``--stdio`` and ``--http`` select the foreground transports
instead. See ``partcad_service_json_rpc.__main__`` for the executable entry
point.

The daemon owns both the warm PartCAD context (so clients skip the ~1.6s
``import partcad`` and the package reload) *and* the sandboxed Python runtimes
that every CAD wrapper runs in. The latter is why a client cannot simply do the
work itself: those runtimes belong to the daemon's environment and need not
exist on the client side at all.
"""

__version__ = "0.8.11"
