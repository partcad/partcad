#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The client's side of the Windows named-pipe daemon, without Windows.

`pc` on Windows used to start a one-shot stdio service for every command, and
the pipe client in `partcad_client.client` was reached by nothing -- which is
how it kept a bug: it read the pipe through the raw, unbuffered file it is
opened as, where a read returns what has arrived so far, and `read_message`
takes a body shorter than its length for the end of the stream. Now that every
Windows command connects through it, these pin what it does with a stand-in for
the pipe, so that they run on every leg of the matrix: a module of its own, with
no AF_UNIX guard (see `test_daemon_windows.py` for why that matters).

What is not exercised here is the operating system's half: opening a real pipe,
and `CancelIoEx` ending a read blocked in it.
"""

import contextlib
import io
import os
import threading
import time

import pytest

from partcad_client import client as client_module
from partcad_client.client import DaemonStalled
from partcad_utils.framing import read_message, write_message
from partcad_utils.win_pipe import pipe_name

PIPE = r"\\.\pipe\partcad-0123456789abcdef"


class FakePipe(io.RawIOBase):
    """The client's end of a named pipe: answers come back a few bytes per read.

    ``answer`` is what the service sends, ``chunk`` the most one read returns --
    which is what a pipe does with a message larger than what has arrived.
    ``block`` makes a read wait until :meth:`cancel` ends it with an error, which
    is what ``CancelIoEx`` does to a read blocked in a real pipe.
    """

    def __init__(self, answer: bytes = b"", chunk: int = 7, block: bool = False):
        self._answer = answer
        self._chunk = chunk
        self._block = block
        self._cancelled = threading.Event()
        self.written = bytearray()

    def readable(self):
        return True

    def writable(self):
        return True

    def readinto(self, buffer):
        if self._block:
            self._cancelled.wait(30)
            raise OSError(22, "Invalid argument")  # what a cancelled read leaves behind
        n = min(len(buffer), self._chunk, len(self._answer))
        buffer[:n] = self._answer[:n]
        self._answer = self._answer[n:]
        return n

    def write(self, data):
        self.written += data
        return len(data)

    def cancel(self):
        self._cancelled.set()


def _framed(*messages) -> bytes:
    stream = io.BytesIO()
    for message in messages:
        write_message(stream, message)
    return stream.getvalue()


@contextlib.contextmanager
def _pretending_to_be_windows():
    """Take the Windows branches; see `test_daemon_windows.py` for why not a fixture."""
    saved = os.name
    os.name = "nt"
    try:
        yield
    finally:
        os.name = saved


# Big enough that no pipe hands it over in one read.
LARGE = {"jsonrpc": "2.0", "id": 1, "result": {"data": "x" * 200_000}}


def test_a_raw_pipe_read_is_short(monkeypatch):
    """The bug, on its own: the unbuffered file reads a large body short, as the end of the stream."""
    assert read_message(FakePipe(_framed(LARGE))) is None


def test_a_large_answer_arrives_whole_over_the_pipe(monkeypatch):
    pipe = FakePipe(_framed({"jsonrpc": "2.0", "method": "log", "params": {"kind": "log"}}, LARGE))
    monkeypatch.setattr(client_module, "_pipe_file", lambda name: pipe)

    conn = client_module._open_endpoint(PIPE)
    try:
        assert conn.call("version") == LARGE["result"]
    finally:
        conn.close()
    assert read_message(io.BytesIO(bytes(pipe.written)))["method"] == "version"


def test_a_stalled_pipe_is_cancelled_and_reported(monkeypatch):
    """A pipe takes no timeout, so the watchdog ends the read -- by cancelling it.

    Not by killing anything: the daemon at the other end serves other clients.
    """
    pipe = FakePipe(block=True)
    monkeypatch.setattr(client_module, "_pipe_file", lambda name: pipe)
    monkeypatch.setattr(client_module, "_cancel_pipe_read", lambda raw: raw.cancel())
    monkeypatch.setenv("PC_DAEMON_IDLE_TIMEOUT", "0.2")

    conn = client_module._open_endpoint(PIPE)
    try:
        started = time.monotonic()
        with pytest.raises(DaemonStalled, match="stopped responding"):
            conn.call("wedged")
        assert time.monotonic() - started < 15
    finally:
        conn.close()


def test_an_error_reading_a_pipe_nobody_cancelled_is_not_a_stall(monkeypatch):
    class Broken(FakePipe):
        def readinto(self, buffer):
            raise OSError(5, "Input/output error")

    monkeypatch.setattr(client_module, "_pipe_file", lambda name: Broken())
    conn = client_module._open_endpoint(PIPE)
    try:
        with pytest.raises(OSError) as caught:
            conn.call("version")
        assert not isinstance(caught.value, DaemonStalled)
    finally:
        conn.close()


def test_a_busy_pipe_is_waited_out(monkeypatch):
    """Every instance taken is the moment between a connection and the next instance."""
    attempts = []
    pipe = FakePipe()

    def fake_open(name, mode, buffering):
        attempts.append((name, mode, buffering))
        if len(attempts) < 3:
            raise OSError(22, "Invalid argument")  # how the C runtime reports ERROR_PIPE_BUSY
        return pipe

    monkeypatch.setattr(client_module, "open", fake_open, raising=False)
    assert client_module._pipe_file(PIPE) is pipe
    assert attempts == [(PIPE, "r+b", 0)] * 3


def test_a_pipe_nobody_serves_is_reported_at_once(monkeypatch):
    attempts = []

    def fake_open(name, mode, buffering):
        attempts.append(name)
        raise FileNotFoundError(2, "No such file or directory", name)

    monkeypatch.setattr(client_module, "open", fake_open, raising=False)
    with pytest.raises(FileNotFoundError):
        client_module._pipe_file(PIPE)
    assert attempts == [PIPE]


def test_windows_commands_use_the_pipe_daemon_rather_than_a_service_of_their_own(monkeypatch, tmp_path):
    """`connect()` on Windows: the workspace's pipe, and no launcher when it answers."""
    opened = []
    pipe = FakePipe(_framed({"jsonrpc": "2.0", "id": 1, "result": {"partcad": "x"}}))

    def pipe_file(name):
        opened.append(name)
        return pipe

    monkeypatch.setattr(client_module, "_pipe_file", pipe_file)
    monkeypatch.setattr(client_module, "start_daemon", _refuse("the launcher"))
    monkeypatch.setattr(client_module, "_connect_stdio", _refuse("a one-shot stdio service"))

    with _pretending_to_be_windows():
        conn = client_module.connect(cwd=str(tmp_path))
    try:
        assert conn.call("version") == {"partcad": "x"}
    finally:
        conn.close()
    assert opened == [pipe_name(str(tmp_path))]


def test_windows_starts_the_pipe_daemon_when_none_answers(monkeypatch, tmp_path):
    started = []
    pipe = FakePipe(_framed({"jsonrpc": "2.0", "id": 1, "result": "pong"}))

    def pipe_file(name):
        if not started:
            raise FileNotFoundError(2, "No such file or directory", name)
        return pipe

    def start_daemon(cwd=None, extra_args=(), replace_different=False):
        started.append((cwd, replace_different))
        return pipe_name(str(tmp_path))

    monkeypatch.setattr(client_module, "_pipe_file", pipe_file)
    monkeypatch.setattr(client_module, "start_daemon", start_daemon)
    monkeypatch.setattr(client_module, "_connect_stdio", _refuse("a one-shot stdio service"))

    with _pretending_to_be_windows():
        conn = client_module.connect(cwd=str(tmp_path))
    try:
        assert conn.call("ping") == "pong"
    finally:
        conn.close()
    assert started == [(str(tmp_path), False)]


def _refuse(what):
    def refuse(*args, **kwargs):
        raise AssertionError("%s was not expected to run" % what)

    return refuse
