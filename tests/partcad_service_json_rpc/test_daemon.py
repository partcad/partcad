#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for starting the daemon (the non-forking parts).

Where the socket lives and whether anything answers on it is
`partcad_utils.workspace`, tested there; stopping and enumerating daemons is
`partcad_client.daemon`, tested there. What is left here is the service's
own half: `ensure_daemon` reusing a daemon that is already serving, and its
Windows branch -- which no CI runner executes, so it is driven here with
`os.name` forced to "nt".
"""

import contextlib
import os
import pathlib
import shutil
import socket
import tempfile
import threading
import time

import pytest
from partcad_service_json_rpc import daemon
from partcad_service_json_rpc import win_pipe as service_win_pipe
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.methods import build_registry
from partcad_service_json_rpc.transport.socket_server import SocketServer
from partcad_utils import win_pipe as rendezvous

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)

WORKSPACE = r"C:\ws"
SANDBOX_ARGV = ["--python-sandbox", "conda"]


@pytest.fixture
def socket_dir():
    """A directory short enough to hold an AF_UNIX socket path.

    ``sun_path`` is 104 bytes on macOS and 108 on Linux; pytest's ``tmp_path``
    spends most of that before the socket name is appended, so binding under it
    fails with "AF_UNIX path too long". Defined per-module because this package
    and ``partcad`` both have a ``tests`` package, so two ``tests.conftest``
    modules would collide in a run that collects both.
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


def _serve(path, registry):
    server = SocketServer(Session(), registry)
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    _wait_until_listening(path)
    return server


def test_ensure_daemon_returns_existing_socket_when_alive(monkeypatch, capsys):
    # A short HOME under /tmp keeps the AF_UNIX socket path under ~108 chars
    # (pytest's tmp_path is far too deep once the workspace subdirs are added).
    import shutil
    import tempfile

    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    root = "/some/root"
    sock = daemon.socket_path(root)
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    server = _serve(sock, build_registry())
    try:
        returned = daemon.ensure_daemon(lambda: Session(), root_path=root)
        assert returned == sock
        assert capsys.readouterr().out.strip() == sock  # path printed to stdout
    finally:
        server.stop()
        shutil.rmtree(home, ignore_errors=True)


@contextlib.contextmanager
def _pretending_to_be_windows():
    """Run ``ensure_daemon``'s Windows branch here, where CI actually runs.

    There is no Windows runner in this repository's CI, and the branch shipped
    importing a name its own ``win_pipe`` does not define (``is_pipe_alive``,
    which lives in ``partcad_utils.win_pipe`` with the rest of the rendezvous).
    Every ``partcad-json-rpc --socket`` on Windows therefore died of an
    ImportError on the first line of the branch, before it spawned anything, and
    all the editor extension could report was "exited 1".

    A context manager rather than a fixture, because ``os.name`` has to be back
    before pytest formats a failure: while it says "nt", ``pathlib.Path`` builds
    a ``WindowsPath`` and reporting a failed assertion dies of
    NotImplementedError -- turning a regression here into an INTERNALERROR
    instead of a message naming it.
    """
    saved = os.name
    os.name = "nt"
    try:
        yield
    finally:
        os.name = saved


@pytest.fixture
def spawned(monkeypatch):
    """Records ``(root, extra_args)`` of every daemon spawn, and spawns nothing.

    Patched in as a module attribute rather than by faking the import: the
    branch under test still runs its own ``from ... import ...``, so a name that
    moves away again fails here instead of on a user's machine.
    """
    calls = []
    monkeypatch.setattr(service_win_pipe, "spawn_pipe_daemon", lambda root, extra=(): calls.append((root, list(extra))))
    return calls


def _answers(monkeypatch, *replies):
    """Make ``is_pipe_alive`` return ``replies`` in turn, then its last value."""
    remaining = list(replies)
    monkeypatch.setattr(
        rendezvous,
        "is_pipe_alive",
        lambda name, timeout=1.0: remaining.pop(0) if len(remaining) > 1 else remaining[0],
    )


def test_windows_reuses_the_daemon_already_serving_the_pipe(spawned, monkeypatch, capsys):
    _answers(monkeypatch, True)
    with _pretending_to_be_windows():
        pipe = daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE, daemon_argv=SANDBOX_ARGV)
    assert pipe == rendezvous.pipe_name(WORKSPACE)
    assert capsys.readouterr().out.strip() == pipe  # the endpoint goes to stdout
    assert spawned == []


def test_windows_starts_a_daemon_and_waits_for_it_to_answer(spawned, monkeypatch, capsys):
    # Dead, then alive: the launcher must not name the pipe until something is
    # serving it, because connecting to a pipe that does not exist yet fails
    # outright rather than waiting.
    _answers(monkeypatch, False, True)
    with _pretending_to_be_windows():
        pipe = daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE, daemon_argv=SANDBOX_ARGV)
    assert capsys.readouterr().out.strip() == pipe
    # The settings the launcher was given reach the daemon. Windows has no
    # `fork`, so nothing carries them across on its own: without this the
    # daemon behind `pc --python-sandbox conda daemon start` served with the
    # defaults, and said nothing about it.
    assert spawned == [(WORKSPACE, SANDBOX_ARGV)]


def test_windows_reports_a_daemon_that_never_starts_serving(spawned, monkeypatch):
    monkeypatch.setattr(daemon, "START_TIMEOUT", 0.05)
    _answers(monkeypatch, False)
    with pytest.raises(RuntimeError, match="did not start serving"):
        with _pretending_to_be_windows():
            daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE)
    assert spawned == [(WORKSPACE, [])]
