#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the threaded AF_UNIX JSON-RPC socket server."""

import os
import socket
import threading
import time

import pytest

from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport.framing import read_message, write_message
from partcad_service_json_rpc.transport.socket_server import SocketServer

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


def _serve(tmp_path, registry, session=None):
    path = str(tmp_path / "socket")
    server = SocketServer(session or Session(), registry)
    thread = threading.Thread(target=server.serve_unix, args=(path,), daemon=True)
    thread.start()
    for _ in range(200):
        if os.path.exists(path):
            break
        time.sleep(0.01)
    return server, path, thread


def _connect(path):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(path)
    return client.makefile("rwb"), client


def test_socket_request_response_round_trip(tmp_path):
    server, path, _ = _serve(tmp_path, {"ping": lambda s, p: "pong"})
    try:
        f, c = _connect(path)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert read_message(f) == {"jsonrpc": "2.0", "id": 1, "result": "pong"}
        c.close()
    finally:
        server.stop()


def test_notifications_route_to_the_calling_connection_before_the_response(tmp_path):
    def go(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "ok"

    server, path, _ = _serve(tmp_path, {"go": go})
    try:
        f, c = _connect(path)
        write_message(f, {"jsonrpc": "2.0", "id": 7, "method": "go"})
        first = read_message(f)
        second = read_message(f)
        assert first == {"jsonrpc": "2.0", "method": events.ITEMS, "params": {"name": "//"}}
        assert second == {"jsonrpc": "2.0", "id": 7, "result": "ok"}
        c.close()
    finally:
        server.stop()


def test_daemon_stop_responds_then_shuts_down_and_unlinks(tmp_path):
    server, path, thread = _serve(tmp_path, {})
    f, c = _connect(path)
    write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "daemon.stop"})
    resp = read_message(f)
    assert resp["result"]["stopped"] is True
    c.close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert not os.path.exists(path)


def test_dispatch_is_serialized_across_connections(tmp_path):
    events_log = []

    def slow(session, params):
        events_log.append(("start", params["n"]))
        time.sleep(0.2)
        events_log.append(("end", params["n"]))
        return params["n"]

    server, path, _ = _serve(tmp_path, {"slow": slow})
    try:
        responses = {}

        def call(n):
            f, c = _connect(path)
            write_message(f, {"jsonrpc": "2.0", "id": n, "method": "slow", "params": {"n": n}})
            responses[n] = read_message(f)
            c.close()

        t1 = threading.Thread(target=call, args=(1,))
        t2 = threading.Thread(target=call, args=(2,))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both requests completed...
        assert responses[1]["result"] == 1
        assert responses[2]["result"] == 2
        # ...and dispatch never interleaved: each start is immediately followed
        # by its own end (the lock serializes the handler entirely).
        assert len(events_log) == 4
        for k in range(0, len(events_log), 2):
            assert events_log[k][0] == "start"
            assert events_log[k + 1] == ("end", events_log[k][1])
    finally:
        server.stop()
