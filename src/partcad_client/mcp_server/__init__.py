#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc mcp`: the Model Context Protocol server an AI agent drives PartCAD through.

It is a **client** of the workspace daemon, exactly as `pc` itself is, which is
why it lives here and not in `partcad_service_json_rpc`. The agent starts it as
a subprocess on its own machine and speaks MCP to it on stdio; it speaks framed
JSON-RPC to the daemon over the daemon's socket (`partcad_client.client`), and
the daemon does the work -- loading packages, running CAD scripts in their
sandboxes, rendering. So an agent needs nothing installed but PartCAD, and a
daemon never learns that an agent exists.

The shape follows the two CAD applications that drive themselves the same way,
cadcraft and solidcraft (`<app>-cli mcp`), and for the same reasons:

* **A small set of curated tools with real schemas** for what an agent does all
  the time -- see what a package holds, read an object's declaration, look at
  it, test it, write it out -- plus **one generic** ``execute`` that reaches
  every daemon method, with ``list_methods`` to find them. The daemon has about
  seventy methods and only a dozen deserve a schema of their own; the rest stay
  reachable without this file having to grow a tool for each.
* **Errors are results.** A daemon error, an object that failed to build, a test
  that failed, a path outside the workspace: all come back as a tool result
  with ``isError`` set and the daemon's log attached, which is what an agent can
  read and act on. Only a malformed call is a protocol error.
* **Files stay inside the workspace** unless the user widens that with
  ``--allow-path`` (see :mod:`.sandbox`).

What is different is that most of PartCAD's methods return nothing and *log*
their answer -- `pc list` prints a table -- so every tool collects the log
lines the daemon streams while it works (:class:`.bridge.Outcome`) and returns
them with whatever result there was.
"""

from .bridge import Bridge
from .sandbox import PathScope


def serve(workspace: str, allow_paths=(), allow_any_path: bool = False) -> None:
    """Serve MCP on stdin/stdout for the PartCAD workspace at ``workspace``.

    Blocks until the client closes stdin. Nothing is started up front: the
    daemon is reached on the first tool call that needs it, so a client that
    only lists the tools never starts one -- and a server started in a directory
    that is not a package yet still starts, and says so when it is asked to do
    something.
    """
    import logging

    from .server import build_server

    bridge = Bridge(workspace)
    scope = PathScope([bridge.root, *allow_paths], unrestricted=allow_any_path)
    # stderr, which is the one stream an MCP client shows a person and never
    # parses: stdout is the protocol's.
    logging.getLogger("partcad").info("PartCAD MCP server for %s; files reachable: %s", bridge.root, scope.describe())
    try:
        build_server(bridge, scope).run("stdio")
    finally:
        bridge.close()


__all__ = ["Bridge", "PathScope", "serve"]
