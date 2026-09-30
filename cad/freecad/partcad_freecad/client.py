#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A framed JSON-RPC client for the standalone ``partcad-json-rpc`` service.

Mirrors ``partcad_client.client`` (a thin client that does not import
``partcad``), with two differences that matter inside FreeCAD:

* the launcher is an explicit path to the frozen executable, not this
  interpreter -- FreeCAD's Python has no PartCAD in it;
* :meth:`JsonRpcClient.call` is serialized with a lock, because the addon issues
  calls from a worker thread while the Qt main thread stays responsive.
"""

import os
import socket
import subprocess
import threading
from typing import Callable, Optional

from .framing import read_message, write_message

# Do not pop up a console window for the launcher/service on Windows.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Seconds to wait for the local daemon socket to accept a connection.
CONNECT_TIMEOUT = 10.0


class ServiceError(RuntimeError):
    """A JSON-RPC error returned by the service."""

    def __init__(self, error: dict):
        super().__init__(error.get("message", "service error"))
        self.code = error.get("code")
        self.data = error.get("data")


class JsonRpcClient:
    """A framed JSON-RPC client over a single service connection."""

    def __init__(self, read_stream, write_stream, closer: Optional[Callable[[], None]] = None):
        self._read = read_stream
        self._write = write_stream
        self._closer = closer
        self._next_id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params=None, on_event: Optional[Callable[[str, object], None]] = None):
        """Send a request; forward notifications to ``on_event`` until the response."""
        with self._lock:
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
                        raise ServiceError(message["error"])
                    return message.get("result")
                if "method" in message and "id" not in message and on_event is not None:
                    on_event(message["method"], message.get("params"))

    def close(self) -> None:
        if self._closer is not None:
            try:
                self._closer()
            except Exception:  # pylint: disable=broad-except
                pass
            self._closer = None


def start_daemon(executable: str, cwd: Optional[str] = None, extra_args=()) -> str:
    """Ensure a daemon serves the workspace at ``cwd``; return its socket path."""
    result = subprocess.run(
        [executable, "--socket", *extra_args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        creationflags=_NO_WINDOW,
    )
    path = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not path:
        raise RuntimeError("partcad-json-rpc did not print a socket path: %s" % (result.stderr or "").strip())
    return path


def _connect_socket(executable: str, cwd: Optional[str], extra_args) -> JsonRpcClient:
    path = start_daemon(executable, cwd, extra_args)
    if path.startswith("\\\\.\\pipe\\"):  # Windows named pipe
        stream = open(path, "r+b", buffering=0)  # pragma: no cover - Windows only
        return JsonRpcClient(stream, stream, closer=stream.close)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # Bound the connect: the daemon is local and answers immediately or not at
    # all, so a hang here means a stale socket, not slow work. The deadline is
    # then cleared for the session -- PartCAD operations legitimately run for
    # minutes (cloning a repository, building a sandbox, running a CAD script),
    # and a read deadline would abort them mid-flight.
    sock.settimeout(CONNECT_TIMEOUT)
    sock.connect(path)
    sock.settimeout(None)
    stream = sock.makefile("rwb")

    def closer():
        try:
            stream.close()
        finally:
            sock.close()

    return JsonRpcClient(stream, stream, closer=closer)


def _connect_stdio(executable: str, cwd: Optional[str], extra_args) -> JsonRpcClient:
    proc = subprocess.Popen(
        [executable, "--stdio", *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=cwd,
        creationflags=_NO_WINDOW,
    )

    def closer():
        # Closing stdin is what asks the service to exit; the rest is making
        # sure it is actually gone and its pipes are released. A killed child
        # still has to be waited on to be reaped, and the read pipe is the one
        # the client held, so nothing else will close it.
        try:
            proc.stdin.close()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:  # pylint: disable=broad-except
                pass

    return JsonRpcClient(proc.stdout, proc.stdin, closer=closer)


def connect(executable: str, cwd: Optional[str] = None, extra_args=()) -> JsonRpcClient:
    """Connect to the PartCAD service for the package directory ``cwd``.

    Prefers the shared per-workspace daemon (a warm context, shared with the CLI
    and the VS Code extension), falling back to a private one-shot service over
    stdin/stdout when the daemon cannot be started.
    """
    if os.name != "nt":
        try:
            return _connect_socket(executable, cwd, extra_args)
        except Exception:  # pylint: disable=broad-except
            pass  # fall back to a one-shot stdio service
    return _connect_stdio(executable, cwd, extra_args)
