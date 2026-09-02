#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for starting the daemon (the non-forking parts).

Where the socket lives and whether anything answers on it is
`partcad_utils.workspace`, tested there; stopping and enumerating daemons is
`partcad_client.daemon`, tested there. What is left here is the service's
own half: `ensure_daemon` reusing a daemon that is already serving. Its
Windows branch is `test_daemon_windows.py`, which is a separate module because
the AF_UNIX guard below skips this one on the platform that branch is about.
"""

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
