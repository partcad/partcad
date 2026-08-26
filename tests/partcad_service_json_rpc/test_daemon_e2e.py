#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""End-to-end test of the socket daemon started by the real executable."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import pytest

import partcad_service_json_rpc
from partcad_service_json_rpc import daemon
from partcad_utils.framing import read_message, write_message

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


@pytest.fixture
def short_dirs():
    # AF_UNIX socket paths cap at ~108 chars; pytest's tmp_path is far too deep,
    # so use a short HOME/workspace under /tmp for a realistic path length.
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    workdir = tempfile.mkdtemp(prefix="pcw", dir="/tmp")
    try:
        yield home, workdir
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)


def _run_launcher(workdir, env):
    return subprocess.run(
        [sys.executable, "-m", "partcad_service_json_rpc", "--socket"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_socket_daemon_starts_reuses_and_stops(short_dirs):
    home, workdir = short_dirs
    src_root = os.path.dirname(os.path.dirname(partcad_service_json_rpc.__file__))
    env = dict(
        os.environ,
        HOME=home,
        PYTHONPATH=src_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )

    # First launch starts a detached daemon and prints its socket path.
    first = _run_launcher(workdir, env)
    assert first.returncode == 0, first.stderr
    sock = first.stdout.strip()
    assert sock.endswith("/socket")
    assert os.path.exists(sock)
    assert daemon.is_alive(sock)

    try:
        # Second launch finds the live daemon and prints the same path (no new one).
        second = _run_launcher(workdir, env)
        assert second.stdout.strip() == sock
    finally:
        # Tell the daemon to stop and confirm it goes away.
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock)
        stream = client.makefile("rwb")
        write_message(stream, {"jsonrpc": "2.0", "id": 1, "method": "daemon.stop"})
        read_message(stream)
        client.close()

    for _ in range(50):
        if not daemon.is_alive(sock):
            break
        time.sleep(0.1)
    assert not daemon.is_alive(sock)
