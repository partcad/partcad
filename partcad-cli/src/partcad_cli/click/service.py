#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Run a CLI command through the PartCAD daemon.

This is the seam the CLI migration turns on: a command's body calls
:func:`run` with a JSON-RPC method + params instead of importing ``partcad`` and
doing the work in-process. ``run`` ensures the workspace daemon, brackets the
call in a client-side telemetry span (reported directly by the CLI now that
``partcad_utils.telemetry`` is cheaply importable — no telemetry crosses the RPC
boundary), streams the operation's forwarded log events into the shared local
renderer, and returns the result.
"""

import logging
import os

import rich_click as click
from partcad_service_json_rpc import client as _client

import partcad_utils.logging_remote_client as _remote_client
import partcad_utils.telemetry as _telemetry

# Deliberate emitter.info()/warn()/error() notifications carry a bare string;
# render them as log lines through the same client-side renderer as the streamed
# `log` events (which carry a structured dict).
_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def _on_event(method, params) -> None:
    """Render a server-to-client notification through the shared logging setup."""
    if method == "log":
        _remote_client.handle(params or {})
    elif method in _LEVELS:
        message = params if isinstance(params, str) else str(params)
        _remote_client.handle({"kind": "log", "levelno": _LEVELS[method], "message": message})


# PartCAD-specific error codes (mirror operations.INVALID_CONFIG/USAGE_ERROR),
# rendered like the legacy in-process CLI did.
_INVALID_CONFIG = -32001
_USAGE_ERROR = -32002


def run(cli_ctx, method: str, params: dict = None, span_name: str = None, needs_context: bool = False):
    """Execute ``method`` on the daemon, wrapped in a client-side telemetry span.

    When ``needs_context`` is set, a context is created (or reused) on the daemon
    for this workspace's URL and its id is passed to the operation. Returns the
    operation result. Raises ``click.ClickException`` (so the CLI exits non-zero
    with a clean message) if the daemon reports an error.
    """
    conn = _client.connect()
    try:
        with _telemetry.start_as_current_span(span_name or method, attributes={"action": "cli " + method}):
            call_params = dict(params or {})
            if needs_context:
                # -p/--path (a partcad.yaml or directory), else the current dir,
                # as a file:// URL. The daemon persists the context and returns
                # its id, which context-aware operations carry.
                path = getattr(cli_ctx, "path", None) or os.getcwd()
                url = "file://" + os.path.abspath(path)
                result = conn.call("context.create", {"url": url}, on_event=_on_event)
                call_params["context"] = result.get("context")
            return conn.call(method, call_params, on_event=_on_event)
    except _client.DaemonError as e:
        code = getattr(e, "code", None)
        if code == _INVALID_CONFIG:
            # Match the legacy get_partcad_context behavior.
            raise click.ClickException("Invalid configuration file")
        if code == _USAGE_ERROR:
            # Match commands that raised click.UsageError (exit code 2).
            raise click.UsageError(str(e))
        raise click.ClickException(str(e))
    finally:
        conn.close()
