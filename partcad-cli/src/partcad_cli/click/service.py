#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Run a CLI command through the PartCAD daemon.

This is the seam the CLI migration turns on: a command's body calls
:func:`run` with a JSON-RPC method + params instead of importing ``partcad`` and
doing the work in-process. ``run`` ensures the workspace daemon, brackets the
call in a telemetry span (reported upstream by the daemon), streams the
operation's log/terminal events to the local streams, and returns the result.
"""

import base64
import logging
import sys

import rich_click as click
from partcad_service_json_rpc import client as _client

_log = logging.getLogger("partcad")


def _render(method, params) -> None:
    """Render a server-to-client notification on the local streams."""
    if method == "info":
        _log.info(params)
    elif method == "warn":
        _log.warning(params)
    elif method == "error":
        _log.error(params)
    elif method == "terminal":
        try:
            sys.stdout.buffer.write(base64.b64decode(params.get("line", "")))
            sys.stdout.flush()
        except Exception:  # pylint: disable=broad-except
            pass


def run(cli_ctx, method: str, params: dict = None, span_name: str = None):
    """Execute ``method`` on the daemon, wrapped in a telemetry span.

    Returns the operation result. Raises ``click.ClickException`` (so the CLI
    exits non-zero with a clean message) if the daemon reports an error.
    """
    conn = _client.connect()
    span = None
    try:
        span = conn.call(
            "telemetry.start",
            {"name": span_name or method, "attributes": {"action": "cli " + method}},
        ).get("span")
        result = conn.call(method, params or {}, on_event=_render)
        conn.call("telemetry.end", {"span": span})
        return result
    except _client.DaemonError as e:
        if span is not None:
            try:
                conn.call("telemetry.end", {"span": span, "status": "error", "message": str(e)})
            except Exception:  # pylint: disable=broad-except
                pass
        raise click.ClickException(str(e))
    finally:
        conn.close()
