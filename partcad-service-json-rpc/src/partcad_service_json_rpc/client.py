#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Client helpers for talking to the PartCAD service.

Used by the CLI (a thin client) and available to any other Python caller.

On POSIX, :func:`connect` uses the shared per-workspace **socket daemon** (a warm
context): ``start_daemon`` runs the ``partcad-json-rpc`` launcher and returns its
socket path. On Windows, where the socket daemon is not yet available, it falls
back to launching a one-shot ``partcad-json-rpc --stdio`` service and talking to
it over its pipes. Either way the caller stays a thin client that does not import
``partcad``; :class:`DaemonClient` speaks framed JSON-RPC and delivers server
notifications to an optional callback while waiting for the matching response.
"""

import os
import socket
import subprocess
import sys
from typing import Callable, Optional

from .transport.framing import read_message, write_message


class DaemonError(RuntimeError):
    """A JSON-RPC error returned by the service."""

    def __init__(self, error: dict):
        super().__init__(error.get("message", "service error"))
        self.code = error.get("code")
        self.data = error.get("data")


def launcher_argv() -> list:
    """Command that runs the ``partcad-json-rpc`` executable for this install."""
    if getattr(sys, "frozen", False):
        exe = "partcad-json-rpc" + (".exe" if os.name == "nt" else "")
        return [os.path.join(os.path.dirname(sys.executable), exe)]
    return [sys.executable, "-m", "partcad_service_json_rpc"]


def start_daemon(cwd: Optional[str] = None, extra_args=()) -> str:
    """Ensure a socket daemon serves the workspace at ``cwd``; return its path.

    POSIX only (the socket daemon uses AF_UNIX and fork). On Windows use the
    stdio fallback via :func:`connect`.
    """
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


class DaemonClient:
    """A framed JSON-RPC client over a single service connection."""

    def __init__(self, read_stream, write_stream, closer: Optional[Callable[[], None]] = None):
        self._read = read_stream
        self._write = write_stream
        self._closer = closer
        self._next_id = 0

    def call(self, method: str, params=None, on_event: Optional[Callable[[str, object], None]] = None):
        """Send a request; forward notifications to ``on_event`` until the response."""
        self._next_id += 1
        request_id = self._next_id
        # Only default when params is absent: an explicit [] or {} is a valid
        # (empty positional / empty named) parameter list and must be preserved.
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        request["params"] = {} if params is None else params
        write_message(self._write, request)
        while True:
            message = read_message(self._read)
            if message is None:
                raise RuntimeError("the PartCAD service closed the connection")
            if message.get("id") == request_id and ("result" in message or "error" in message):
                if "error" in message:
                    raise DaemonError(message["error"])
                return message.get("result")
            if "method" in message and "id" not in message and on_event is not None:
                on_event(message["method"], message.get("params"))

    def close(self) -> None:
        if self._closer is not None:
            try:
                self._closer()
            except Exception:  # pylint: disable=broad-except
                pass


def _connect_socket(cwd: Optional[str], extra_args) -> DaemonClient:
    path = start_daemon(cwd, extra_args)
    if path.startswith("\\\\.\\pipe\\"):  # Windows named pipe
        stream = open(path, "r+b", buffering=0)  # pragma: no cover - Windows only
        return DaemonClient(stream, stream, closer=stream.close)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    stream = sock.makefile("rwb")

    def closer():
        try:
            stream.close()
        finally:
            sock.close()

    return DaemonClient(stream, stream, closer=closer)


def _connect_stdio(cwd: Optional[str], extra_args) -> DaemonClient:
    proc = subprocess.Popen(
        launcher_argv() + ["--stdio", *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=cwd,
    )

    def closer():
        try:
            proc.stdin.close()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # pylint: disable=broad-except
            try:
                proc.kill()
            except Exception:  # pylint: disable=broad-except
                pass

    return DaemonClient(proc.stdout, proc.stdin, closer=closer)


def connect(cwd: Optional[str] = None, extra_args=()) -> DaemonClient:
    """Connect to the PartCAD service for this workspace.

    POSIX: the shared per-workspace socket daemon (warm context), falling back to
    a one-shot stdio service if it cannot be started. Windows: a one-shot stdio
    service (the socket daemon is not available there yet).
    """
    if os.name != "nt":
        try:
            return _connect_socket(cwd, extra_args)
        except Exception:  # pylint: disable=broad-except
            pass  # fall back to a one-shot stdio service
    return _connect_stdio(cwd, extra_args)
