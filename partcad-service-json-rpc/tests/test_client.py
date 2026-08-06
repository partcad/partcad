#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the DaemonClient (request/response + notification delivery)."""

import pathlib
import shutil
import socket
import tempfile
import threading
import time

import pytest
from partcad_service_json_rpc.client import DaemonClient, DaemonError
from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport.socket_server import SocketServer

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


@pytest.fixture
def socket_dir():
    """A directory short enough to hold an AF_UNIX socket path.

    ``sun_path`` is a fixed-size field -- 104 bytes on macOS, 108 on Linux --
    and pytest's ``tmp_path`` spends most of that before the socket name is
    appended: on macOS it sits under
    ``/private/var/folders/<hash>/T/pytest-of-<user>/pytest-<n>/<test-name><n>/``,
    where a descriptive test name alone pushes a bind past the limit and fails
    with "AF_UNIX path too long". ``/tmp`` keeps the prefix to a few characters,
    which is also what a real daemon socket looks like (it lives under
    ``~/.partcad/workspaces/<hash>/``).

    Defined per-module rather than in a conftest: this package and ``partcad``
    both have a ``tests`` package, so two ``tests.conftest`` modules collide
    when a single pytest run collects both.
    """
    path = tempfile.mkdtemp(prefix="pcs", dir="/tmp")
    try:
        yield pathlib.Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _wait_until_listening(path, timeout=5.0):
    """Block until the server at ``path`` accepts connections.

    ``serve_unix()`` creates the socket *file* at bind() and only accepts after
    listen(), so waiting for the file to exist returns too early and the next
    connect is refused - a race a loaded CI runner loses (ECONNREFUSED on both
    Linux and macOS). Probing with a real connect is the only signal that means
    "ready".
    """
    deadline = time.monotonic() + timeout
    while True:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(path)
            return
        except (ConnectionRefusedError, FileNotFoundError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
        finally:
            probe.close()


def _serve(socket_dir, registry):
    path = str(socket_dir / "socket")
    server = SocketServer(Session(), registry)
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    _wait_until_listening(path)
    return server, path


def _client(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    stream = sock.makefile("rwb")
    return DaemonClient(stream, stream, closer=lambda: (stream.close(), sock.close()))


def test_client_call_returns_result(socket_dir):
    server, path = _serve(socket_dir, {"ping": lambda s, p: {"echo": p}})
    try:
        client = _client(path)
        assert client.call("ping", {"x": 1}) == {"echo": {"x": 1}}
        client.close()
    finally:
        server.stop()


def test_client_delivers_notifications_before_result(socket_dir):
    def go(session, params):
        session.emitter.emit(events.INFO, "working")
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "done"

    server, path = _serve(socket_dir, {"go": go})
    try:
        seen = []
        client = _client(path)
        result = client.call("go", {}, on_event=lambda m, p: seen.append((m, p)))
        assert result == "done"
        assert seen == [(events.INFO, "working"), (events.ITEMS, {"name": "//"})]
        client.close()
    finally:
        server.stop()


def test_client_raises_daemon_error_on_error_response(socket_dir):
    server, path = _serve(socket_dir, {})  # rpc.discover exists; "nope" does not
    try:
        client = _client(path)
        with pytest.raises(DaemonError):
            client.call("nope")
        client.close()
    finally:
        server.stop()
