#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How `connect()` finds the daemon: directly, and through the launcher only when it has to.

Every `pc` command used to run the `partcad-json-rpc --socket` launcher to be
told where the workspace's daemon listens -- a process start, a third of a
second, to learn a path that `partcad_utils.workspace` computes from a hash.
`connect()` now computes it itself and connects; the launcher is run only when
nothing answers there. These pin both halves: that a daemon which answers is
used without the launcher, and that everything else -- no socket, a stale one
-- is still the launcher's to decide. The address is the shared one, and one
test holds it to what a launcher run in the same directory would compute.
"""

import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from partcad_client import client as client_module
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport.socket_server import SocketServer
from partcad_utils import workspace

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


@pytest.fixture
def home(monkeypatch):
    """A home directory short enough for an AF_UNIX path under ``~/.partcad/workspaces``.

    See 'socket_dir' in 'test_client.py' for why not pytest's 'tmp_path'.
    """
    path = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", path)
    try:
        yield pathlib.Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def ws(home):
    """A workspace of its own: a directory with no 'partcad.yaml' above it."""
    path = home / "ws"
    path.mkdir()
    return path


@pytest.fixture
def launcher(monkeypatch):
    """Records every launcher run; ``endpoint`` is what it answers with.

    Nothing is spawned: the question is whether it would have been.
    """

    class Launcher:
        endpoint = None
        calls = []

        def __call__(self, cwd=None, extra_args=(), replace_different=False):
            self.calls.append((cwd, tuple(extra_args), replace_different))
            if self.endpoint is None:
                raise RuntimeError("the launcher was not expected to run")
            return self.endpoint

    fake = Launcher()
    fake.calls = []
    monkeypatch.setattr(client_module, "start_daemon", fake)
    return fake


def _serve(path: str, registry):
    """A daemon's socket server at ``path``, accepting before this returns."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    server = SocketServer(Session(), registry)
    threading.Thread(target=server.serve_unix, args=(path,), daemon=True).start()
    deadline = time.monotonic() + 10
    while not workspace.is_listening(path):
        assert time.monotonic() < deadline, "the stand-in daemon never started listening"
        time.sleep(0.01)
    return server


def test_a_daemon_answering_at_the_workspace_endpoint_is_used_without_the_launcher(ws, launcher):
    server = _serve(client_module.workspace_endpoint(str(ws)), {"ping": lambda s, p: "pong"})
    try:
        conn = client_module.connect(cwd=str(ws))
        try:
            assert conn.call("ping") == "pong"
        finally:
            conn.close()
    finally:
        server.stop()
    assert launcher.calls == []


def test_with_nothing_at_the_endpoint_the_launcher_is_asked(ws, home, launcher):
    # The launcher's answer is a socket somewhere else entirely, so that being
    # served at all proves the client went where the launcher said.
    elsewhere = str(home / "elsewhere" / "socket")
    server = _serve(elsewhere, {"ping": lambda s, p: "from the launcher's daemon"})
    launcher.endpoint = elsewhere
    try:
        conn = client_module.connect(cwd=str(ws), extra_args=["--offline"])
        try:
            assert conn.call("ping") == "from the launcher's daemon"
        finally:
            conn.close()
    finally:
        server.stop()
    # Asked as before: with the caller's flags, which only a daemon the launcher
    # has to start would ever see, and never to replace one.
    assert launcher.calls == [(str(ws), ("--offline",), False)]


def test_a_stale_socket_is_left_to_the_launcher(ws, home, launcher):
    """A socket file outlives a daemon that was killed; nothing listens on it.

    Replacing it is the launcher's, under its lock -- a client that unlinked it
    itself would be racing every other client of the workspace.
    """
    stale = client_module.workspace_endpoint(str(ws))
    os.makedirs(os.path.dirname(stale), exist_ok=True)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(stale)
    dead.close()
    assert os.path.exists(stale)

    elsewhere = str(home / "elsewhere" / "socket")
    server = _serve(elsewhere, {"ping": lambda s, p: "pong"})
    launcher.endpoint = elsewhere
    try:
        conn = client_module.connect(cwd=str(ws))
        conn.close()
    finally:
        server.stop()
    assert len(launcher.calls) == 1
    assert os.path.exists(stale), "the client removed a socket that is the launcher's to replace"


def test_the_endpoint_is_the_one_a_launcher_in_that_directory_computes(ws):
    """Through a symbolic link, too: the launcher hashes what *its* getcwd() says.

    A launcher is run with ``cwd=`` the directory it is given, and the operating
    system reports that directory with its links resolved. Hashed from the
    spelling the caller passed instead, the client would look for -- and, not
    finding it, have the launcher start -- a daemon at an address nobody serves.
    """
    real = ws / "package"
    real.mkdir()
    (real / "partcad.yaml").write_text("name: x\n")
    link = ws / "link"
    link.symlink_to(real, target_is_directory=True)

    script = "from partcad_utils import workspace; print(workspace.socket_path(workspace.determine_root_path()))"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    for start in (real, link, link / "."):
        launcher_says = subprocess.run(
            [sys.executable, "-c", script], cwd=str(start), capture_output=True, text=True, check=True, env=env
        ).stdout.strip()
        assert client_module.workspace_endpoint(str(start)) == launcher_says


def test_the_endpoint_of_this_directory_is_found_from_it(ws, monkeypatch):
    monkeypatch.chdir(ws)
    assert client_module.workspace_endpoint() == workspace.socket_path(os.getcwd())
