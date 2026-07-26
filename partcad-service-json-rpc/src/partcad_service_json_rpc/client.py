#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Client helpers for talking to the workspace daemon.

Used by the CLI (a thin client of the daemon) and available to any other Python
caller. ``start_daemon`` runs the ``partcad-json-rpc`` launcher (which starts a
detached daemon if none is alive) and returns its socket path; ``DaemonClient``
speaks framed JSON-RPC over that socket, delivering server notifications to an
optional callback while waiting for the matching response.
"""

import os
import socket
import subprocess
import sys
from typing import Callable, Optional

from .transport.framing import read_message, write_message


class DaemonError(RuntimeError):
    """A JSON-RPC error returned by the daemon."""

    def __init__(self, error: dict):
        super().__init__(error.get("message", "daemon error"))
        self.code = error.get("code")
        self.data = error.get("data")


def launcher_argv() -> list:
    """Command that runs the ``partcad-json-rpc`` launcher for this install."""
    if getattr(sys, "frozen", False):
        exe = "partcad-json-rpc" + (".exe" if os.name == "nt" else "")
        return [os.path.join(os.path.dirname(sys.executable), exe)]
    return [sys.executable, "-m", "partcad_service_json_rpc"]


def start_daemon(cwd: Optional[str] = None, extra_args=()) -> str:
    """Ensure a daemon serves the workspace at ``cwd`` and return its socket path."""
    result = subprocess.run(
        launcher_argv() + ["--socket", *extra_args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    path = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not path:
        raise RuntimeError("partcad-json-rpc did not print a socket path: %s" % (result.stderr or "").strip())
    return path


def _connect_endpoint(path: str):
    """Return a readable/writable binary stream to the daemon endpoint."""
    if path.startswith("\\\\.\\pipe\\"):  # Windows named pipe
        return open(path, "r+b", buffering=0)  # pragma: no cover - Windows only
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    stream = sock.makefile("rwb")
    stream._pc_socket = sock  # keep the socket alive alongside the stream
    return stream


class DaemonClient:
    """A framed JSON-RPC client over a single daemon connection."""

    def __init__(self, path: str):
        self.path = path
        self._stream = _connect_endpoint(path)
        self._next_id = 0

    def call(self, method: str, params=None, on_event: Optional[Callable[[str, object], None]] = None):
        """Send a request; forward notifications to ``on_event`` until the response."""
        self._next_id += 1
        request_id = self._next_id
        write_message(self._stream, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        while True:
            message = read_message(self._stream)
            if message is None:
                raise RuntimeError("the PartCAD daemon closed the connection")
            if message.get("id") == request_id and ("result" in message or "error" in message):
                if "error" in message:
                    raise DaemonError(message["error"])
                return message.get("result")
            if "method" in message and "id" not in message and on_event is not None:
                on_event(message["method"], message.get("params"))

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            pass


def connect(cwd: Optional[str] = None, extra_args=()) -> DaemonClient:
    """Ensure the workspace daemon is running and return a connected client."""
    return DaemonClient(start_daemon(cwd, extra_args))
