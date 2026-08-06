#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the DaemonClient (request/response + notification delivery)."""

import os
import socket
import threading
import time

import pytest
from partcad_service_json_rpc.client import DaemonClient, DaemonError
from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport.socket_server import SocketServer

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


def _serve(socket_dir, registry):
    path = str(socket_dir / "socket")
    server = SocketServer(Session(), registry)
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    for _ in range(200):
        if os.path.exists(path):
            break
        time.sleep(0.01)
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
