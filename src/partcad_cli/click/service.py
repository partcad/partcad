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
from pathlib import Path

import partcad_utils.logging_remote_client as _remote_client
import partcad_utils.telemetry as _telemetry
import rich_click as click
from partcad_client import client as _client
from partcad_utils.user_config import user_config as _user_config

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
                # its id, which context-aware operations carry. Path.as_uri()
                # produces a well-formed URL on every platform (Windows drive
                # letters and spaces included) -- "file://" + a raw path does not.
                path = getattr(cli_ctx, "path", None) or os.getcwd()
                url = Path(path).resolve().as_uri()
                # This invocation's resolved user configuration travels with the
                # request, and the daemon builds the context from it rather than
                # from its own. The daemon is warm and shared per workspace, so
                # its own configuration is whatever the environment held when
                # something first started it -- not what this command was
                # invoked with. Anything resolved here ('--devel-index',
                # '--force-update', '--offline', the 'PC_*' environment, the
                # config file) would otherwise be ignored the moment a daemon
                # was already running.
                result = conn.call(
                    "context.create",
                    {"url": url, "userConfig": _user_config.to_dict()},
                    on_event=_on_event,
                )
                call_params["context"] = result.get("context")
            return conn.call(method, call_params, on_event=_on_event)
    except _client.DaemonStalled as e:
        # The command is over either way; this only decides how it reads. A
        # ClickException exits 1 with one line, where the traceback a bare
        # RuntimeError produces would bury the report the client has already
        # written to the log -- and would suggest a fault in the CLI rather than
        # in the service it was waiting for.
        raise click.ClickException(str(e))
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
