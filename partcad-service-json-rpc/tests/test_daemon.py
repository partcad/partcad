#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for daemon discovery/liveness (the non-forking parts)."""

import os
import pathlib
import shutil
import socket
import tempfile
import threading
import time

import pytest
from partcad_service_json_rpc import daemon
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.methods import build_registry
from partcad_service_json_rpc.transport.socket_server import SocketServer

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


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


def test_workspace_hash_is_deterministic_and_16_hex():
    h = daemon.workspace_hash("/some/root")
    assert h == daemon.workspace_hash("/some/root")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)
    assert daemon.workspace_hash("/other") != h


def test_socket_path_lives_under_partcad_workspaces(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = daemon.socket_path("/some/root")
    expected = os.path.join(str(tmp_path), ".partcad", "workspaces", daemon.workspace_hash("/some/root"), "socket")
    assert p == expected


def test_determine_root_path_walks_up_to_the_topmost_partcad_yaml(tmp_path):
    root = tmp_path / "proj"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "partcad.yaml").write_text("desc: test\n")
    (root / "a" / "partcad.yaml").write_text("desc: nested\n")
    assert daemon.determine_root_path(str(sub)) == str(root.resolve())


def test_determine_root_path_without_partcad_yaml_is_the_directory_itself(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert daemon.determine_root_path(str(d)) == str(d.resolve())


def _serve(path, registry):
    server = SocketServer(Session(), registry)
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    # Wait until the server is *accepting*, not merely until the socket file
    # exists. serve_unix() binds -- which creates the file -- and only then
    # calls listen(); a client that connects in between gets ECONNREFUSED.
    # `_server_sock` is assigned after listen() returns, so it is the first
    # observable moment at which a connection can succeed.
    for _ in range(500):
        if server._server_sock is not None:
            break
        time.sleep(0.01)
    return server


def test_is_alive_false_when_socket_absent(tmp_path):
    assert daemon.is_alive(str(tmp_path / "nope")) is False


def test_is_alive_false_when_socket_file_is_stale(socket_dir):
    stale = socket_dir / "socket"
    stale.write_text("")  # a plain file, nothing listening
    assert daemon.is_alive(str(stale)) is False


def test_is_alive_true_when_a_daemon_is_serving(socket_dir):
    path = str(socket_dir / "socket")
    server = _serve(path, build_registry())
    try:
        assert daemon.is_alive(path) is True
    finally:
        server.stop()


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


# ---------------------------------------------------------------------------
# Stopping daemons, and waiting for them.
#
# An update replaces the files a daemon is running from, so "it acknowledged the
# stop" is not good enough: these are the helpers that make the difference
# between asking and knowing.
# ---------------------------------------------------------------------------


def test_wait_until_stopped_returns_immediately_when_nothing_is_running(socket_dir):
    assert daemon.wait_until_stopped(str(socket_dir), timeout=1.0) is True


def test_wait_until_stopped_is_false_while_a_daemon_is_serving(socket_dir):
    server = _serve(str(socket_dir / "socket"), build_registry())
    try:
        assert daemon.wait_until_stopped(str(socket_dir), timeout=0.5) is False
    finally:
        server.stop()


def test_wait_until_stopped_is_false_while_the_pid_is_still_alive(socket_dir):
    """The socket goes quiet before the process exits; both are checked."""
    (socket_dir / "pid").write_text(str(os.getpid()))
    assert daemon.wait_until_stopped(str(socket_dir), timeout=0.5) is False


def test_wait_until_stopped_ignores_a_stale_pid_file(socket_dir):
    # A daemon killed outright never runs its cleanup handler, so the pid file
    # outlives it. Waiting forever on that would block every future update.
    (socket_dir / "pid").write_text("2147483646")
    assert daemon.wait_until_stopped(str(socket_dir), timeout=1.0) is True


def test_live_daemon_dirs_finds_a_serving_daemon(monkeypatch, socket_dir):
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    wdir = os.path.join(daemon.workspaces_dir(), "deadbeefdeadbeef")
    os.makedirs(wdir, exist_ok=True)
    server = _serve(os.path.join(wdir, "socket"), build_registry())
    try:
        assert daemon.live_daemon_dirs() == [wdir]
    finally:
        server.stop()
        shutil.rmtree(home, ignore_errors=True)


def test_live_daemon_dirs_ignores_a_stale_socket(monkeypatch):
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    wdir = os.path.join(daemon.workspaces_dir(), "deadbeefdeadbeef")
    os.makedirs(wdir, exist_ok=True)
    pathlib.Path(wdir, "socket").write_text("")  # nothing listening
    try:
        assert daemon.live_daemon_dirs() == []
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_stop_all_daemons_stops_every_workspace(monkeypatch):
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    servers, wdirs = [], []
    for name in ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"):
        wdir = os.path.join(daemon.workspaces_dir(), name)
        os.makedirs(wdir, exist_ok=True)
        servers.append(_serve(os.path.join(wdir, "socket"), build_registry()))
        wdirs.append(wdir)
    try:
        stopped = daemon.stop_all_daemons(timeout=10.0)
        assert sorted(stopped) == sorted(wdirs)
        assert daemon.live_daemon_dirs() == []
    finally:
        for server in servers:
            server.stop()
        shutil.rmtree(home, ignore_errors=True)


def test_stop_all_daemons_is_a_no_op_without_daemons(monkeypatch):
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    try:
        assert daemon.stop_all_daemons(timeout=1.0) == []
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_stop_daemon_waits_for_the_daemon_to_be_gone(monkeypatch):
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    root = "/some/root"
    sock = daemon.socket_path(root)
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    server = _serve(sock, build_registry())
    try:
        assert daemon.stop_daemon(root, wait=10.0) is True
        assert daemon.is_alive(sock) is False
    finally:
        server.stop()
        shutil.rmtree(home, ignore_errors=True)
