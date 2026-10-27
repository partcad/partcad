#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the threaded AF_UNIX JSON-RPC socket server."""

import os
import pathlib
import shutil
import socket
import tempfile
import threading
import time

import pytest

from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport.socket_server import SocketServer
from partcad_utils.framing import as_bytes, read_message, write_message

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


def _serve(socket_dir, registry, session=None):
    path = str(socket_dir / "socket")
    server = SocketServer(session or Session(), registry)
    thread = threading.Thread(target=server.serve_unix, args=(path,), daemon=True)
    thread.start()
    # Wait until the server is *accepting*, not merely until the socket file
    # exists: serve_unix() binds -- which creates the file -- and only then
    # calls listen(), so a client that connects in between gets ECONNREFUSED.
    # A real connect is the only signal that means "ready"; `_server_sock`
    # being assigned after listen() is close, but it is an internal detail and
    # still leaves the accept loop unentered.
    _wait_until_listening(path)
    return server, path, thread


def _connect(path):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(path)
    return client.makefile("rwb"), client


def test_socket_request_response_round_trip(socket_dir):
    server, path, _ = _serve(socket_dir, {"ping": lambda s, p: "pong"})
    try:
        f, c = _connect(path)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert read_message(f) == {"jsonrpc": "2.0", "id": 1, "result": "pong"}
        c.close()
    finally:
        server.stop()


def test_notifications_route_to_the_calling_connection_before_the_response(socket_dir):
    def go(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "ok"

    server, path, _ = _serve(socket_dir, {"go": go})
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


def test_daemon_stop_responds_then_shuts_down_and_unlinks(socket_dir):
    server, path, thread = _serve(socket_dir, {})
    f, c = _connect(path)
    write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "daemon.stop"})
    resp = read_message(f)
    assert resp["result"]["stopped"] is True
    c.close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    # The socket is unlinked by stop(), which the daemon.stop handler runs on
    # the *connection* thread -- not the accept-loop `thread` joined above. And
    # stop() sets the stop flag before it unlinks, so the accept loop can see
    # the flag and exit (ending `thread`) in the window before the unlink runs.
    # Joining `thread` therefore does not imply the file is gone; poll for it.
    # Mirror image of the startup race #496 fixed by waiting for listen()
    # rather than for the socket file to appear.
    for _ in range(300):
        if not os.path.exists(path):
            break
        time.sleep(0.01)
    assert not os.path.exists(path)


def test_dispatch_is_serialized_across_connections(socket_dir):
    events_log = []

    def slow(session, params):
        events_log.append(("start", params["n"]))
        time.sleep(0.2)
        events_log.append(("end", params["n"]))
        return params["n"]

    server, path, _ = _serve(socket_dir, {"slow": slow})
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


def test_a_busy_daemon_still_answers_whether_it_is_alive_and_can_be_stopped(socket_dir):
    """Every other request waits its turn; the liveness probe does not.

    Queued behind a long render -- or behind one that never ended, which is
    what a sandbox that died used to leave -- the probe timed out, so the daemon
    was taken for gone, and `pc daemon stop`, which asks it first, answered
    "No PartCAD daemon was running for this workspace" to the very user the
    stalled client had just told to run it.
    """
    from partcad_client.daemon import _stop_socket_daemon
    from partcad_utils.workspace import is_alive

    entered = threading.Event()
    release = threading.Event()

    def busy(session, params):
        entered.set()
        release.wait(30)
        return "done"

    def discover(session, params):
        return {"methods": []}

    server, path, thread = _serve(socket_dir, {"busy": busy, "rpc.discover": discover})
    try:
        f, c = _connect(path)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "busy"})
        assert entered.wait(5)

        assert is_alive(path)
        assert _stop_socket_daemon(path)
        thread.join(timeout=5)
        assert not thread.is_alive()
        c.close()
    finally:
        release.set()
        server.stop()


def test_each_connection_is_sent_files_the_way_its_client_reads_them(socket_dir):
    # One daemon, two clients of different versions: the one that said it reads
    # attachments gets the bytes, the one that did not gets the base64 it always
    # got -- per connection, because a setting on the shared session would be one
    # client deciding for the other.
    server, path, _ = _serve(socket_dir, {"render": lambda s, p: {"content": b"\x89PNG" * 1000}})
    try:
        new, new_socket = _connect(path)
        old, old_socket = _connect(path)
        write_message(new, {"jsonrpc": "2.0", "id": 1, "method": "render"}, accept_attachments=True)
        write_message(old, {"jsonrpc": "2.0", "id": 1, "method": "render"})
        attached = read_message(new)["result"]["content"]
        encoded = read_message(old)["result"]["content"]
        assert attached == b"\x89PNG" * 1000
        assert isinstance(encoded, str)
        assert as_bytes(encoded) == attached
        # And it stays so for the rest of the connection.
        write_message(new, {"jsonrpc": "2.0", "id": 2, "method": "render"})
        assert isinstance(read_message(new)["result"]["content"], bytes)
        new_socket.close()
        old_socket.close()
    finally:
        server.stop()


def test_each_connection_gets_the_log_display_in_the_encoding_it_asked_for(socket_dir):
    """`log.mode {"text": true}` is per connection, like the renderer it configures.

    An editor extension from before reads only the base64 `line`, and the daemon
    it shares may be newer; one that says it reads `text` gets the text itself.
    """
    import base64
    import logging

    def speak(session, params):
        session.emitter.emit(
            "log", {"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "héllo \x1b"}
        )
        return "said"

    def drawn(f, request_id):
        """Every `terminal` notification's params up to the answer to ``request_id``."""
        params = []
        while True:
            message = read_message(f)
            if message.get("id") == request_id:
                return params
            if message.get("method") == events.TERMINAL:
                params.append(message["params"])

    server, path, _ = _serve(socket_dir, {"speak": speak})
    try:
        new, new_socket = _connect(path)
        old, old_socket = _connect(path)

        write_message(new, {"jsonrpc": "2.0", "id": 1, "method": "log.mode", "params": {"ansi": True, "text": True}})
        assert read_message(new) == {"jsonrpc": "2.0", "id": 1, "result": {"ansi": True, "text": True}}
        write_message(old, {"jsonrpc": "2.0", "id": 1, "method": "log.mode", "params": {"ansi": True}})
        assert read_message(old) == {"jsonrpc": "2.0", "id": 1, "result": {"ansi": True}}

        write_message(new, {"jsonrpc": "2.0", "id": 2, "method": "speak"})
        as_text = drawn(new, 2)
        write_message(old, {"jsonrpc": "2.0", "id": 2, "method": "speak"})
        as_base64 = drawn(old, 2)

        assert as_text and all(set(p) == {events.TERMINAL_TEXT} for p in as_text)
        assert as_base64 and all(set(p) == {events.TERMINAL_LINE} for p in as_base64)
        text = "".join(p[events.TERMINAL_TEXT] for p in as_text)
        assert "héllo \x1b" in text
        assert "".join(base64.b64decode(p[events.TERMINAL_LINE]).decode("utf-8") for p in as_base64) == text

        new_socket.close()
        old_socket.close()
    finally:
        server.stop()


def test_the_daemon_client_says_it_reads_attachments(socket_dir):
    from partcad_client.client import DaemonClient

    server, path, _ = _serve(socket_dir, {"render": lambda s, p: {"content": b"\x00\x01"}})
    try:
        stream, sock = _connect(path)
        client = DaemonClient(stream, stream, closer=sock.close)
        assert client.call("render") == {"content": b"\x00\x01"}
        client.close()
    finally:
        server.stop()
