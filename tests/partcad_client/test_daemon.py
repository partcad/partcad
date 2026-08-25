#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the client's half of daemon handling.

Stopping a daemon, knowing it has actually gone, and finding the ones running on
this machine. `pc upgrade` replaces the files every one of them is executing, so
"it acknowledged the stop" is not good enough: this is what makes the difference
between asking and knowing.

The daemon here is a fake that speaks the protocol -- `rpc.discover` and
`daemon.stop` -- rather than the real service, so this package's tests do not
depend on the package it talks to. The real pairing is covered by
`tests/partcad_service_json_rpc/test_daemon_e2e.py`.
"""

import os
import pathlib
import shutil
import socket
import tempfile
import threading

import pytest
from partcad_client import daemon
from partcad_utils.framing import read_message, write_message

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


class FakeDaemon:
    """Answers ``rpc.discover``, and stops when told to -- like the real one.

    Optionally ignores ``daemon.stop`` (``obstinate=True``), which is the case
    the update has to survive rather than hang on.

    It writes no pid file. A real daemon is its own process, so its pid dies with
    it; this one lives inside the test process, whose pid never dies -- writing
    it would make `wait_until_stopped` wait for the test itself to exit. The pid
    half of the check is exercised on its own below, where the value written is
    the point.
    """

    def __init__(self, wdir, obstinate=False):
        self.wdir = str(wdir)
        os.makedirs(self.wdir, exist_ok=True)
        self.path = os.path.join(self.wdir, "socket")
        self.obstinate = obstinate
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(8)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stopped.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn, conn.makefile("rwb") as stream:
                request = read_message(stream)
                if not isinstance(request, dict):
                    continue
                if request.get("method") == "daemon.stop" and not self.obstinate:
                    write_message(stream, {"jsonrpc": "2.0", "id": request.get("id"), "result": {"stopped": True}})
                    self.stop()
                    return
                write_message(stream, {"jsonrpc": "2.0", "id": request.get("id"), "result": {"methods": []}})

    def stop(self):
        self._stopped.set()
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def home(monkeypatch):
    """A short HOME under /tmp, so AF_UNIX paths stay under the ~108-char limit."""
    path = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", path)
    try:
        yield pathlib.Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _workspace(index: int) -> str:
    return os.path.join(daemon.workspaces_dir(), "%016x" % index)


# ---------------------------------------------------------------------------
# Waiting for a daemon to actually be gone
# ---------------------------------------------------------------------------


def test_wait_until_stopped_returns_immediately_when_nothing_is_running(home):
    wdir = _workspace(1)
    os.makedirs(wdir, exist_ok=True)
    assert daemon.wait_until_stopped(wdir, timeout=1.0) is True


def test_wait_until_stopped_is_false_while_a_daemon_is_serving(home):
    fake = FakeDaemon(_workspace(1))
    try:
        assert daemon.wait_until_stopped(fake.wdir, timeout=0.5) is False
    finally:
        fake.stop()


def test_wait_until_stopped_is_false_while_the_pid_is_still_alive(home):
    """The socket goes quiet before the process exits; both signals are checked."""
    wdir = _workspace(1)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, "pid"), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    assert daemon.wait_until_stopped(wdir, timeout=0.5) is False


def test_wait_until_stopped_ignores_a_stale_pid_file(home):
    # A daemon killed outright never runs its cleanup handler, so the pid file
    # outlives it. Waiting forever on that would block every future update.
    wdir = _workspace(1)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, "pid"), "w", encoding="utf-8") as f:
        f.write("2147483646")
    assert daemon.wait_until_stopped(wdir, timeout=1.0) is True


# ---------------------------------------------------------------------------
# Stopping one, and stopping all
# ---------------------------------------------------------------------------


def test_stop_daemon_waits_for_the_daemon_to_be_gone(home, monkeypatch):
    root = "/some/root"
    monkeypatch.setattr(daemon, "determine_root_path", lambda *a, **kw: root)
    fake = FakeDaemon(os.path.dirname(daemon.socket_path(root)))
    try:
        assert daemon.stop_daemon(root, wait=10.0) is True
        assert daemon.is_alive(fake.path) is False
    finally:
        fake.stop()


def test_stop_daemon_is_false_when_nothing_is_running(home, monkeypatch):
    monkeypatch.setattr(daemon, "determine_root_path", lambda *a, **kw: "/nothing/here")
    assert daemon.stop_daemon() is False


def test_live_daemon_dirs_finds_every_serving_daemon(home):
    fakes = [FakeDaemon(_workspace(i)) for i in range(3)]
    try:
        assert daemon.live_daemon_dirs() == sorted(f.wdir for f in fakes)
    finally:
        for fake in fakes:
            fake.stop()


def test_live_daemon_dirs_ignores_a_stale_socket(home):
    wdir = _workspace(1)
    os.makedirs(wdir, exist_ok=True)
    pathlib.Path(wdir, "socket").write_text("")  # nothing listening
    assert daemon.live_daemon_dirs() == []


def test_live_daemon_dirs_is_empty_without_a_workspaces_directory(home):
    assert daemon.live_daemon_dirs() == []


def test_stop_all_daemons_stops_every_workspace(home):
    """The requirement: an update replaces files all of them are executing."""
    fakes = [FakeDaemon(_workspace(i)) for i in range(3)]
    try:
        stopped = daemon.stop_all_daemons(timeout=10.0)
        assert sorted(stopped) == sorted(f.wdir for f in fakes)
        assert daemon.live_daemon_dirs() == []
    finally:
        for fake in fakes:
            fake.stop()


def test_stop_all_daemons_reports_only_the_ones_that_went(home):
    """A daemon that ignores the stop must not be counted as stopped."""
    willing = FakeDaemon(_workspace(0))
    obstinate = FakeDaemon(_workspace(1), obstinate=True)
    try:
        stopped = daemon.stop_all_daemons(timeout=1.0)
        assert stopped == [willing.wdir]
    finally:
        willing.stop()
        obstinate.stop()


def test_stop_all_daemons_is_a_no_op_without_daemons(home):
    assert daemon.stop_all_daemons(timeout=1.0) == []


def test_the_addressing_is_the_one_from_partcad_utils():
    """Re-exported, not reimplemented: two copies are two things to disagree."""
    from partcad_utils import workspace

    assert daemon.socket_path is workspace.socket_path
    assert daemon.workspace_hash is workspace.workspace_hash
    assert daemon.determine_root_path is workspace.determine_root_path
    assert daemon.is_alive is workspace.is_alive
