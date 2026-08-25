#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the client/daemon rendezvous: the address, and the liveness probe.

Deliberately free of `partcad-service-json-rpc`: what is checked here is the
*contract* -- an address computed the same way on both sides, and a probe that
believes only an answer. The fake below speaks that contract in twenty lines,
which is the point; if the real daemon ever stopped satisfying it, that is a
break in the contract and not in this test.
"""

import os
import pathlib
import shutil
import socket
import tempfile
import threading

import pytest
from partcad_utils import workspace
from partcad_utils.framing import read_message, write_message

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


@pytest.fixture
def socket_dir():
    """A directory short enough to hold an AF_UNIX socket path.

    ``sun_path`` is 104 bytes on macOS and 108 on Linux; pytest's ``tmp_path``
    spends most of that before the socket name is appended, so binding under it
    fails with "AF_UNIX path too long".
    """
    path = tempfile.mkdtemp(prefix="pcs", dir="/tmp")
    try:
        yield pathlib.Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeDaemon:
    """Answers ``rpc.discover`` on a Unix socket, and nothing else."""

    def __init__(self, path):
        self.path = str(path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(8)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn, conn.makefile("rwb") as stream:
                request = read_message(stream)
                if isinstance(request, dict):
                    write_message(stream, {"jsonrpc": "2.0", "id": request.get("id"), "result": {"methods": []}})

    def stop(self):
        self._stop = True
        self._sock.close()


# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------


def test_workspace_hash_is_deterministic_and_16_hex():
    h = workspace.workspace_hash("/some/root")
    assert h == workspace.workspace_hash("/some/root")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)
    assert workspace.workspace_hash("/other") != h


def test_socket_path_lives_under_partcad_workspaces(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = workspace.socket_path("/some/root")
    expected = os.path.join(str(tmp_path), ".partcad", "workspaces", workspace.workspace_hash("/some/root"), "socket")
    assert p == expected


def test_workspace_dir_is_under_workspaces_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert workspace.workspace_dir("/some/root").startswith(workspace.workspaces_dir() + os.sep)


def test_pid_path_sits_beside_the_socket(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    wdir = workspace.workspace_dir("/some/root")
    assert workspace.pid_path(wdir) == os.path.join(wdir, "pid")
    assert os.path.dirname(workspace.socket_path("/some/root")) == wdir


def test_determine_root_path_walks_up_to_the_topmost_partcad_yaml(tmp_path):
    root = tmp_path / "proj"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "partcad.yaml").write_text("desc: test\n")
    (root / "a" / "partcad.yaml").write_text("desc: nested\n")
    assert workspace.determine_root_path(str(sub)) == str(root.resolve())


def test_determine_root_path_without_partcad_yaml_is_the_directory_itself(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert workspace.determine_root_path(str(d)) == str(d.resolve())


def test_determine_root_path_from_a_file_uses_its_directory(tmp_path):
    f = tmp_path / "partcad.yaml"
    f.write_text("desc: test\n")
    assert workspace.determine_root_path(str(f)) == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def test_is_alive_false_when_socket_absent(tmp_path):
    assert workspace.is_alive(str(tmp_path / "nope")) is False


def test_is_alive_false_when_socket_file_is_stale(socket_dir):
    """A socket file outlives a daemon that was killed; only an answer counts."""
    stale = socket_dir / "socket"
    stale.write_text("")  # a plain file, nothing listening
    assert workspace.is_alive(str(stale)) is False


def test_is_alive_true_when_something_answers(socket_dir):
    fake = FakeDaemon(socket_dir / "socket")
    try:
        assert workspace.is_alive(fake.path) is True
    finally:
        fake.stop()
