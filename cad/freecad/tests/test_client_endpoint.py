#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The launcher is asked where the daemon is once per package directory, not once per connection.

The addon cannot import the rendezvous that says where a workspace's daemon
listens, and must not copy it, so it asks the launcher -- the frozen bundle, a
process start each time. Its answer is a function of the workspace, so it is
remembered, and the launcher is asked again only when nothing takes a
connection there. Driven against a real socket and a stand-in launcher.
"""

import os
import shutil
import socket
import tempfile
import threading

import pytest
from partcad_freecad import client
from partcad_freecad.framing import read_message, write_message

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("AF_UNIX not available on this platform", allow_module_level=True)


class Daemon(threading.Thread):
    """Answers every request on a socket with the request's own method name."""

    daemon = True

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(path)
        self.listener.listen(8)

    def run(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _serve(conn):
        stream = conn.makefile("rwb")
        try:
            while True:
                request = read_message(stream)
                if request is None:
                    return
                write_message(stream, {"jsonrpc": "2.0", "id": request["id"], "result": request["method"]})
        except OSError:
            return
        finally:
            conn.close()

    def stop(self):
        # What a daemon that goes away leaves: no socket file, nothing listening.
        self.listener.close()
        os.unlink(self.path)


@pytest.fixture
def launcher(monkeypatch):
    """A stand-in launcher: starts a daemon if none is running, names its socket, counts its runs."""
    directory = tempfile.mkdtemp(prefix="pcf", dir="/tmp")

    class Launcher:
        path = os.path.join(directory, "socket")
        runs = []
        daemon = None

        def __call__(self, executable, cwd=None, extra_args=()):
            self.runs.append((executable, cwd))
            if self.daemon is None:
                self.daemon = Daemon(self.path)
                self.daemon.start()
            return self.path

        def stop_daemon(self):
            if self.daemon is not None:
                self.daemon.stop()
                self.daemon = None

    fake = Launcher()
    fake.runs = []
    monkeypatch.setattr(client, "start_daemon", fake)
    # Nothing remembered from another test.
    monkeypatch.setattr(client, "_ENDPOINTS", {})
    try:
        yield fake
    finally:
        fake.stop_daemon()
        shutil.rmtree(directory, ignore_errors=True)


def test_the_launcher_is_asked_once_per_package_directory(launcher):
    for _ in range(3):
        conn = client.connect("/bundle/partcad-json-rpc", "/w")
        assert conn.call("info") == "info"
        conn.close()
    assert launcher.runs == [("/bundle/partcad-json-rpc", "/w")]


def test_the_launcher_is_asked_again_when_its_daemon_is_gone(launcher):
    client.connect("/bundle/partcad-json-rpc", "/w").close()
    launcher.stop_daemon()

    conn = client.connect("/bundle/partcad-json-rpc", "/w")
    assert conn.call("info") == "info"
    conn.close()
    assert len(launcher.runs) == 2


def test_a_successor_at_the_same_endpoint_is_simply_used(launcher):
    """A daemon that restarted listens where the last one did: nothing to ask."""
    client.connect("/bundle/partcad-json-rpc", "/w").close()
    launcher.stop_daemon()
    launcher.daemon = Daemon(launcher.path)
    launcher.daemon.start()

    client.connect("/bundle/partcad-json-rpc", "/w").close()
    assert len(launcher.runs) == 1


def test_each_package_directory_has_its_own_answer(launcher):
    client.connect("/bundle/partcad-json-rpc", "/w").close()
    client.connect("/bundle/partcad-json-rpc", "/v").close()
    client.connect("/bundle/partcad-json-rpc", "/w").close()
    assert [cwd for _, cwd in launcher.runs] == ["/w", "/v"]
