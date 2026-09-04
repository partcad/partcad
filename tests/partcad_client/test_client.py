#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the DaemonClient (request/response + notification delivery)."""

import io
import logging
import os
import pathlib
import shutil
import socket
import tempfile
import threading
import time

import pytest
from partcad_client import client as client_module
from partcad_client.client import DaemonClient, DaemonError, DaemonStalled
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
    # Wait until the server is *accepting*, not merely until the socket file
    # exists: serve_unix() binds -- which creates the file -- and only then
    # calls listen(), so a client that connects in between gets ECONNREFUSED.
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


def _stalling_client(path, timeout):
    """A client bounded like the real socket one: a timeout on the socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    sock.settimeout(timeout)
    stream = sock.makefile("rwb")
    return DaemonClient(
        stream,
        stream,
        closer=lambda: (stream.close(), sock.close()),
        timeout=timeout,
        endpoint=path,
    )


def test_client_gives_up_on_a_service_that_stops_answering(socket_dir):
    """A handler that never returns must not hold the client forever.

    Regression: 'pc test' deadlocked inside the daemon, and because the client
    waited on the response with no bound, the CLI sat in 'framing.read_message'
    until CI's own watchdog killed the job 40 minutes later.
    """
    release = threading.Event()

    def wedged(session, params):
        release.wait(30)  # bounded so a failure here cannot hang the suite
        return "eventually"

    server, path = _serve(socket_dir, {"wedged": wedged})
    try:
        client = _stalling_client(path, 0.5)
        started = time.monotonic()
        with pytest.raises(DaemonStalled) as caught:
            client.call("wedged")
        waited = time.monotonic() - started
        assert waited < 15, "gave up after %.1fs, which is not the bound it was given" % waited
        # Says what stopped and what it was doing, so the report is actionable
        # without the caller already knowing which command it was running.
        assert "stopped responding" in str(caught.value)
        assert "wedged" in str(caught.value)
        client.close()
    finally:
        release.set()
        server.stop()


def test_the_stall_report_names_where_to_look(socket_dir, caplog):
    """The loud half: the endpoint, the logs and the pid reach the log."""
    release = threading.Event()
    (socket_dir / "pid").write_text("4242", encoding="utf-8")

    server, path = _serve(socket_dir, {"wedged": lambda s, p: release.wait(30)})
    try:
        client = _stalling_client(path, 0.5)
        with caplog.at_level(logging.ERROR, logger="partcad_client.client"):
            with pytest.raises(DaemonStalled):
                client.call("wedged")
        report = "\n".join(r.getMessage() for r in caplog.records)
        assert path in report
        assert str(socket_dir) in report
        assert "4242" in report
        assert "PC_DAEMON_IDLE_TIMEOUT" in report
        client.close()
    finally:
        release.set()
        server.stop()


def test_a_long_but_talkative_call_is_not_cut_off(socket_dir):
    """The bound is on silence, not on how long the operation takes.

    A recursive render runs for minutes and streams an event per action while
    it does. Every one of those pushes the deadline out, or the bound would be
    a limit on how much work a command may do.
    """

    def slow(session, params):
        for _ in range(6):
            time.sleep(0.1)
            session.emitter.emit(events.INFO, "still here")
        return "done"

    server, path = _serve(socket_dir, {"slow": slow})
    try:
        client = _stalling_client(path, 0.35)  # shorter than the whole call
        seen = []
        assert client.call("slow", {}, on_event=lambda m, p: seen.append(m)) == "done"
        assert len(seen) == 6
        client.close()
    finally:
        server.stop()


def test_no_bound_is_applied_when_the_timeout_is_disabled(socket_dir, monkeypatch):
    monkeypatch.setenv("PC_DAEMON_IDLE_TIMEOUT", "0")
    assert client_module.idle_timeout() == 0.0


def test_the_default_bound_is_used_when_the_setting_is_not_a_number(socket_dir, monkeypatch):
    monkeypatch.setenv("PC_DAEMON_IDLE_TIMEOUT", "soon")
    assert client_module.idle_timeout() == client_module.DEFAULT_IDLE_TIMEOUT


def test_the_bound_can_be_set_from_the_environment(socket_dir, monkeypatch):
    monkeypatch.setenv("PC_DAEMON_IDLE_TIMEOUT", "12.5")
    assert client_module.idle_timeout() == 12.5


def test_a_stalled_stdio_service_is_interrupted_rather_than_waited_on():
    """The other half of the bound, for a channel that takes no timeout.

    The stdio service is reached over pipes, which cannot carry a timeout the
    way a socket can, so a watchdog ends the read instead. It is allowed to be
    this blunt only because that service is a child of this process and serves
    nobody else.
    """
    read_fd, write_fd = os.pipe()
    read_stream = os.fdopen(read_fd, "rb")
    killed = threading.Event()

    def interrupt():
        killed.set()
        os.close(write_fd)  # what 'proc.kill()' amounts to for the read

    client = DaemonClient(
        read_stream,
        io.BytesIO(),
        timeout=0.2,
        endpoint="stdio, pid 4242",
        interrupt=interrupt,
    )
    try:
        started = time.monotonic()
        with pytest.raises(DaemonStalled) as caught:
            client.call("wedged")
        assert time.monotonic() - started < 15
        assert killed.is_set(), "the watchdog never interrupted the read"
        # Not reported as the service closing the connection: it did not, this
        # client closed it, and saying otherwise sends the reader looking for a
        # crash that never happened.
        assert "stopped responding" in str(caught.value)
    finally:
        read_stream.close()
