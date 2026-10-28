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

from partcad_service_json_rpc.core import cancellation, events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import REQUEST_CANCELLED
from partcad_service_json_rpc.transport.socket_server import SocketServer
from partcad_service_json_rpc.transport.writer import SocketWriter
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


# ---- reading apart from serving, writing apart from both ---------------------
#
# Each connection is read by a thread of its own and written by another, and
# requests are served one at a time by a third (see 'transport.dispatch'): a
# client that stops reading delays nobody else, and a '$/cancelRequest' reaches
# the request it is about while that request is queued or running.

# Generous: every wait below ends as soon as what it waits for happens, and a
# worker of a parallel run shares the machine with the others.
TIMEOUT = 30


def _flood(session, params):
    payload = "x" * params.get("size", 10000)
    for _ in range(params["n"]):
        session.emitter.emit(events.INFO, payload)
        cancellation.check()
    return "flooded"


def _until_answer(f, request_id):
    """Every notification before the answer to ``request_id``, and the answer."""
    seen = []
    while True:
        message = read_message(f)
        assert message is not None, "the connection closed after %d notifications" % len(seen)
        if message.get("id") == request_id and "method" not in message:
            return seen, message
        seen.append(message)


def _new_threads(before):
    return [t for t in threading.enumerate() if t not in before]


def _close(stream, sock):
    # Both: a socket with a file still made of it is not closed until the file
    # is, and the daemon would go on seeing a client that is still there.
    stream.close()
    sock.close()


def test_a_client_that_stops_reading_delays_nobody_else(socket_dir):
    # Twenty megabytes of events for a client that reads none of them: far more
    # than a socket buffers. They used to be written by the thread serving the
    # request, which blocked on the full socket holding the dispatch lock, and
    # the second client's 'ping' waited for the first client to read.
    server, path, _ = _serve(socket_dir, {"flood": _flood, "ping": lambda s, p: "pong"})
    try:
        stuck, stuck_socket = _connect(path)
        write_message(stuck, {"jsonrpc": "2.0", "id": 1, "method": "flood", "params": {"n": 2000}})

        other, other_socket = _connect(path)
        other_socket.settimeout(TIMEOUT)
        write_message(other, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert read_message(other) == {"jsonrpc": "2.0", "id": 1, "result": "pong"}

        # And the client that was not reading is owed everything, in order,
        # the moment it starts: its events, then its answer.
        stuck_socket.settimeout(TIMEOUT)
        seen, answer = _until_answer(stuck, 1)
        assert len(seen) == 2000 and all(m["method"] == events.INFO for m in seen)
        assert answer["result"] == "flooded"
        _close(stuck, stuck_socket)
        _close(other, other_socket)
    finally:
        server.stop()


def test_a_queued_request_that_is_cancelled_is_answered_at_once_and_never_runs(socket_dir):
    entered, release = threading.Event(), threading.Event()
    ran = []

    def busy(session, params):
        entered.set()
        assert release.wait(TIMEOUT)
        return "done"

    server, path, _ = _serve(socket_dir, {"busy": busy, "quick": lambda s, p: ran.append(p) or "ran"})
    try:
        f, c = _connect(path)
        c.settimeout(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "busy"})
        assert entered.wait(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 2, "method": "quick"})
        write_message(f, {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 2}})

        # While the request ahead of it is still running.
        assert read_message(f) == {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": REQUEST_CANCELLED, "message": "Request cancelled"},
        }
        release.set()
        assert read_message(f)["result"] == "done"
        assert ran == []
        _close(f, c)
    finally:
        release.set()
        server.stop()


def test_a_running_request_that_is_cancelled_stops_at_its_next_safe_point(socket_dir):
    started = threading.Event()
    steps = []

    def long(session, params):
        started.set()
        for step in range(3000):
            steps.append(step)
            cancellation.check()
            time.sleep(0.01)
        return "all of it"

    server, path, _ = _serve(socket_dir, {"long": long})
    try:
        f, c = _connect(path)
        c.settimeout(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 5, "method": "long"})
        assert started.wait(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 5}})
        assert read_message(f)["error"]["code"] == REQUEST_CANCELLED
        assert len(steps) < 3000
        _close(f, c)
    finally:
        server.stop()


def test_a_client_that_goes_away_has_its_request_cancelled(socket_dir):
    # 'pc render -r' interrupted with Ctrl-C: nobody can read what it goes on
    # producing, and the next command would wait for all of it.
    stopped = threading.Event()

    def chatty(session, params):
        try:
            for _ in range(100000):
                session.emitter.info("working")
                cancellation.check()
                time.sleep(0.005)
        except cancellation.RequestCancelled:
            stopped.set()
            raise
        return "finished"

    server, path, _ = _serve(socket_dir, {"chatty": chatty})
    try:
        f, c = _connect(path)
        c.settimeout(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "chatty"})
        assert read_message(f)["method"] == events.INFO
        _close(f, c)
        assert stopped.wait(TIMEOUT)
    finally:
        server.stop()


def test_a_client_that_takes_nothing_for_too_long_is_dropped_and_its_request_cancelled(socket_dir):
    path = str(socket_dir / "socket")
    server = SocketServer(Session(), {"flood": _flood}, write_timeout=0.5)
    thread = threading.Thread(target=server.serve_unix, args=(path,), daemon=True)
    thread.start()
    _wait_until_listening(path)
    try:
        f, c = _connect(path)
        c.settimeout(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "flood", "params": {"n": 100000}})
        # Not reading, for longer than the bound: the connection is shut down,
        # and what the client finds when it does read is what had already
        # reached its buffer, then the end -- no answer, since the request was
        # cancelled rather than run to the end for nobody.
        time.sleep(2)
        messages = []
        while True:
            message = read_message(f)
            if message is None:
                break
            messages.append(message)
        assert messages and all(m.get("method") == events.INFO for m in messages)
        assert len(messages) < 100000
        _close(f, c)
    finally:
        server.stop()


def test_the_threads_of_a_connection_end_with_it(socket_dir):
    before = set(threading.enumerate())
    server, path, thread = _serve(socket_dir, {"ping": lambda s, p: "pong"})
    f, c = _connect(path)
    c.settimeout(TIMEOUT)
    write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert read_message(f)["result"] == "pong"
    assert _new_threads(before)
    _close(f, c)
    server.stop()
    thread.join(TIMEOUT)
    deadline = time.monotonic() + TIMEOUT
    while _new_threads(before) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _new_threads(before) == []


# ---- the writer on its own -------------------------------------------------------


def _pair():
    ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    return ours, theirs


def test_frames_are_sent_whole_and_in_order():
    ours, theirs = _pair()
    writer = SocketWriter(ours)
    try:
        for n in range(500):
            write_message(writer, {"jsonrpc": "2.0", "method": "n", "params": n})
        write_message(writer, {"jsonrpc": "2.0", "id": 1, "result": b"\x00" * 300000}, attachments=True)
        f = theirs.makefile("rb")
        theirs.settimeout(TIMEOUT)
        assert [read_message(f)["params"] for _ in range(500)] == list(range(500))
        assert read_message(f)["result"] == b"\x00" * 300000
        assert writer.wait_sent(TIMEOUT)
        assert writer.dropped is None
    finally:
        writer.close(TIMEOUT)
        ours.close()
        theirs.close()


def test_a_client_that_takes_nothing_for_the_timeout_is_dropped():
    ours, theirs = _pair()
    told = []
    writer = SocketWriter(ours, on_drop=told.append, timeout=0.3)
    try:
        writer.put([b"x" * (32 * 1024 * 1024)])
        assert writer.wait_sent(TIMEOUT)
        assert writer.dropped is not None and "accepted nothing" in writer.dropped
        # Told on the writer's thread just after the waiters are woken.
        deadline = time.monotonic() + TIMEOUT
        while not told and time.monotonic() < deadline:
            time.sleep(0.01)
        assert told == [writer.dropped]
        # Dropped is shut down: what the client reads ends.
        theirs.settimeout(TIMEOUT)
        while theirs.recv(1 << 20):
            pass
        # And nothing more is queued for it, without an error to whoever writes.
        writer.put([b"more"])
    finally:
        writer.close(TIMEOUT)
        ours.close()
        theirs.close()


def test_a_client_that_lets_too_much_pile_up_is_dropped():
    ours, theirs = _pair()
    writer = SocketWriter(ours, timeout=TIMEOUT, max_backlog=1024 * 1024)
    try:
        # One frame bigger than the bound is fine on its own: it is the answer
        # the client asked for. What piles up behind it is what is bounded.
        writer.put([b"x" * (16 * 1024 * 1024)])
        writer.put([b"y" * (200 * 1024)])
        assert writer.dropped is None
        for _ in range(8):
            writer.put([b"y" * (200 * 1024)])
        assert writer.wait_sent(TIMEOUT)
        assert writer.dropped is not None and "stopped reading" in writer.dropped
    finally:
        writer.close(TIMEOUT)
        ours.close()
        theirs.close()


def test_a_client_that_reads_slowly_is_not_dropped():
    ours, theirs = _pair()
    writer = SocketWriter(ours, timeout=1.0, max_backlog=1024 * 1024)
    try:
        # More than the bound, behind a frame being written, but read the whole
        # time -- slowly, a piece every few hundredths of a second.
        writer.put([b"x" * (4 * 1024 * 1024)])
        writer.put([b"y" * (512 * 1024)])
        received = 0
        theirs.settimeout(TIMEOUT)
        while received < 4 * 1024 * 1024 + 512 * 1024:
            chunk = theirs.recv(256 * 1024)
            assert chunk
            received += len(chunk)
            time.sleep(0.02)
        assert writer.wait_sent(TIMEOUT)
        assert writer.dropped is None
    finally:
        writer.close(TIMEOUT)
        ours.close()
        theirs.close()


def test_frames_written_from_several_threads_at_once_never_interleave():
    # The dispatch thread answers with a file while the renderer's ticking
    # thread and the reader write frames of their own: each frame -- header,
    # body, attachments -- is queued whole, whoever else is writing.
    ours, theirs = _pair()
    writer = SocketWriter(ours)
    per_thread = 200

    def write_many(n):
        for i in range(per_thread):
            content = bytes([n]) * (1000 + 37 * i)
            write_message(writer, {"jsonrpc": "2.0", "method": "f", "params": {"n": n, "content": content}}, True)

    threads = [threading.Thread(target=write_many, args=(n,)) for n in range(4)]
    try:
        for thread in threads:
            thread.start()
        f = theirs.makefile("rb")
        theirs.settimeout(TIMEOUT)
        seen = {n: 0 for n in range(4)}
        for _ in range(4 * per_thread):
            message = read_message(f)
            n = message["params"]["n"]
            assert message["params"]["content"] == bytes([n]) * (1000 + 37 * seen[n])
            seen[n] += 1
        assert seen == {n: per_thread for n in range(4)}
    finally:
        for thread in threads:
            thread.join(TIMEOUT)
        writer.close(TIMEOUT)
        ours.close()
        theirs.close()


def test_an_answer_that_cannot_be_sent_is_said_so_and_the_connection_goes_on(socket_dir):
    server, path, _ = _serve(socket_dir, {"odd": lambda s, p: object(), "ping": lambda s, p: "pong"})
    try:
        f, c = _connect(path)
        c.settimeout(TIMEOUT)
        write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "odd"})
        assert read_message(f)["error"]["code"] == -32603
        write_message(f, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert read_message(f) == {"jsonrpc": "2.0", "id": 2, "result": "pong"}
        _close(f, c)
    finally:
        server.stop()
