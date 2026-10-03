#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The daemon restarting when the user configuration changes.

Three halves, tested separately because each can be wrong on its own: noticing
the change (:class:`ConfigWatcher`), deciding when the daemon may leave
(:class:`Connections`), and the socket server actually leaving -- off the map
at once, but only after the connections it still has are done with it.
"""

import os
import pathlib
import shutil
import socket
import tempfile
import threading
import time
import types

import pytest

from partcad_service_json_rpc import config_restart, daemon
from partcad_service_json_rpc.config_restart import ConfigWatcher, Connections
from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_utils.framing import read_message, write_message

TICK = 0.05


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


# ---- noticing ---------------------------------------------------------------


def _watch(path):
    fired = threading.Event()
    watcher = ConfigWatcher(str(path), fired.set, interval=TICK).start()
    return watcher, fired


def test_an_edit_fires_once_it_has_settled(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("pythonSandbox: conda\n")
    watcher, fired = _watch(config)
    try:
        config.write_text("# pythonSandbox: conda\n")
        assert fired.wait(5)
    finally:
        watcher.stop()


def test_saving_the_same_content_is_not_a_change(tmp_path):
    """A 'touch', or an editor saving an unchanged buffer, restarts nothing."""
    config = tmp_path / "config.yaml"
    config.write_text("threadsMax: 2\n")
    watcher, fired = _watch(config)
    try:
        config.write_text("threadsMax: 2\n")
        os.utime(config)
        assert not fired.wait(10 * TICK)
    finally:
        watcher.stop()


@pytest.mark.parametrize("before, after", [(None, "threadsMax: 2\n"), ("threadsMax: 2\n", None)])
def test_creating_or_deleting_the_file_is_a_change(tmp_path, before, after):
    config = tmp_path / "config.yaml"
    if before is not None:
        config.write_text(before)
    watcher, fired = _watch(config)
    try:
        if after is None:
            config.unlink()
        else:
            config.write_text(after)
        assert fired.wait(5)
    finally:
        watcher.stop()


def test_it_can_be_turned_off(monkeypatch, tmp_path):
    monkeypatch.setenv("PC_DAEMON_RESTART_ON_CONFIG", "0")
    assert config_restart.watch(lambda: None, str(tmp_path / "config.yaml")) is None


def test_it_watches_the_file_the_configuration_is_read_from():
    from partcad_utils.user_config import UserConfig

    assert config_restart.config_path() == UserConfig.get_config_path()


# ---- deciding when to leave ---------------------------------------------------


def test_a_connection_is_told_only_once_it_is_idle():
    told = []
    connections = Connections()
    token = connections.add(lambda event, payload: told.append(event))
    connections.begin(token)
    connections.draining.set()

    connections.tell_idle()
    assert told == []
    assert not connections.settled(grace=0)

    connections.end(token)
    assert told == [events.DO_RESTART]


def test_it_is_told_once():
    told = []
    connections = Connections()
    connections.add(lambda event, payload: told.append(event))
    connections.tell_idle()
    connections.tell_idle()
    assert told == [events.DO_RESTART]


def test_an_idle_connection_that_stays_is_waited_for_only_the_grace_period():
    connections = Connections()
    connections.add(lambda event, payload: None)
    connections.tell_idle()
    assert not connections.settled(grace=60)
    assert connections.settled(grace=0)


def test_nobody_left_is_settled():
    connections = Connections()
    token = connections.add(lambda event, payload: None)
    connections.begin(token)
    connections.remove(token)
    assert connections.settled(grace=60)


def test_a_stop_ends_the_drain():
    connections = Connections()
    token = connections.add(lambda event, payload: None)
    connections.begin(token)
    stop = threading.Event()
    stop.set()
    connections.drain(grace=60, until=stop)  # returns rather than waiting on a busy connection


# ---- leaving ----------------------------------------------------------------

needs_unix = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="AF_UNIX not available on this platform")


@pytest.fixture
def socket_dir():
    """Short, for ``sun_path``: see the fixture of the same name in test_socket_server.py."""
    path = tempfile.mkdtemp(prefix="pcr", dir="/tmp")
    try:
        yield pathlib.Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _serve(socket_dir, registry, grace):
    from partcad_service_json_rpc.transport.socket_server import SocketServer

    path = str(socket_dir / "socket")
    server = SocketServer(Session(), registry, restart_grace=grace)
    thread = threading.Thread(target=server.serve_unix, args=(path,), daemon=True)
    thread.start()

    def listening():
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(path)
            return True
        except OSError:
            return False
        finally:
            probe.close()

    assert _wait(listening)
    return server, path, thread


class _Client:
    """A connection that can really be closed.

    Closing the socket alone leaves the descriptor open while its file object
    holds it, and the server then never sees the end of the stream.
    """

    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.file = self.sock.makefile("rwb")

    def close(self):
        self.file.close()
        self.sock.close()


def _connect(path):
    client = _Client(path)
    return client.file, client


@needs_unix
def test_restart_leaves_the_map_at_once_and_tells_who_is_connected(socket_dir):
    server, path, thread = _serve(socket_dir, {"ping": lambda s, p: "pong"}, grace=60)
    f, c = _connect(path)
    write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert read_message(f)["result"] == "pong"

    server.restart()

    # Gone from the rendezvous immediately, so the next client starts another.
    assert not os.path.exists(path)
    assert read_message(f) == {"jsonrpc": "2.0", "method": events.DO_RESTART, "params": None}
    # ...but still serving the connection it has, until that one goes.
    assert thread.is_alive()
    c.close()
    thread.join(timeout=5)
    assert not thread.is_alive()


@needs_unix
def test_restart_waits_for_the_request_in_progress(socket_dir):
    release = threading.Event()

    def slow(session, params):
        release.wait(5)
        return "done"

    server, path, thread = _serve(socket_dir, {"slow": slow}, grace=60)
    f, c = _connect(path)
    write_message(f, {"jsonrpc": "2.0", "id": 1, "method": "slow"})
    assert _wait(lambda: not server._connections.settled(grace=0))

    server.restart()
    time.sleep(0.3)
    assert thread.is_alive()

    release.set()
    # The answer first, then the notice: told while busy, the extension would
    # drop the connection that was waiting for it.
    assert read_message(f) == {"jsonrpc": "2.0", "id": 1, "result": "done"}
    assert read_message(f)["method"] == events.DO_RESTART
    c.close()
    thread.join(timeout=5)
    assert not thread.is_alive()


@needs_unix
def test_a_connection_that_ignores_the_notice_is_not_waited_for_forever(socket_dir):
    server, path, thread = _serve(socket_dir, {}, grace=0.2)
    f, c = _connect(path)
    assert _wait(lambda: not server._connections.settled(grace=60))
    server.restart()
    thread.join(timeout=5)
    assert not thread.is_alive()
    c.close()


@needs_unix
def test_the_old_daemon_leaves_the_new_ones_socket_alone(socket_dir):
    """The drain ends in stop(), which must not unlink what the successor bound."""
    server, path, thread = _serve(socket_dir, {}, grace=60)
    f, c = _connect(path)
    server.restart()
    assert read_message(f)["method"] == events.DO_RESTART

    successor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    successor.bind(path)
    successor.listen(1)
    try:
        c.close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert os.path.exists(path)
    finally:
        successor.close()


def test_the_old_daemon_leaves_the_new_ones_pid_file_alone(tmp_path):
    from partcad_utils.workspace import pid_path

    pid_file = pathlib.Path(pid_path(str(tmp_path)))
    pid_file.write_text(str(os.getpid() + 1))
    daemon._cleanup(str(tmp_path))
    assert pid_file.exists()

    pid_file.write_text(str(os.getpid()))
    daemon._cleanup(str(tmp_path))
    assert not pid_file.exists()


# ---- what a restart is for --------------------------------------------------


def test_the_sandbox_the_daemon_is_started_with_is_the_one_it_uses(monkeypatch):
    """'--python-sandbox' used to set an attribute nothing read."""
    from partcad_service_json_rpc.core import session as session_module

    class _Config:
        # Slots, so that assigning an attribute nobody reads fails here
        # instead of silently doing nothing.
        __slots__ = ("python_sandbox", "log_level")

    config = _Config()
    fake = types.SimpleNamespace(user_config=config)
    monkeypatch.setattr(session_module.importlib, "import_module", lambda name: fake)

    session = Session(settings={"pythonSandbox": "docker"})
    session.load_partcad()
    assert config.python_sandbox == "docker"


def test_the_sandbox_setting_counts_as_declared():
    from partcad_utils.user_config import UserConfig

    config = UserConfig.__new__(UserConfig)
    config.python_sandbox = "docker"
    assert config.python_sandbox_declared


# ---- a launcher that wants a daemon started differently ----------------------


def _serve_with(socket_dir, settings):
    from partcad_service_json_rpc.transport.socket_server import SocketServer

    path = str(socket_dir / "socket")
    server = SocketServer(Session(), {}, restart_grace=60, launch_settings=settings)
    thread = threading.Thread(target=server.serve_unix, args=(path,), daemon=True)
    thread.start()
    assert _wait(lambda: os.path.exists(path) and daemon._socket_ask(path, {}, 1.0) is not None)
    return server, path, thread


@needs_unix
def test_a_daemon_started_the_same_way_is_kept(socket_dir):
    server, path, thread = _serve_with(socket_dir, ["--python-sandbox", "docker"])
    try:
        ask = lambda params: daemon._socket_ask(path, params, 1.0)  # noqa: E731
        assert not daemon._settings_differ(ask, ["--python-sandbox", "docker"])
        assert os.path.exists(path)
    finally:
        server.stop()


@needs_unix
def test_a_daemon_started_another_way_makes_way(socket_dir):
    """The extension's sandbox setting used to stop at whichever daemon was already running."""
    server, path, thread = _serve_with(socket_dir, ["--python-sandbox", "conda"])
    ask = lambda params: daemon._socket_ask(path, params, 1.0)  # noqa: E731
    assert daemon._settings_differ(ask, ["--python-sandbox", "docker"])
    # Gone by the time the answer arrived, so the launcher can bind its own.
    assert not os.path.exists(path)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_a_daemon_that_cannot_answer_is_kept():
    """An older daemon says "method not found"; stopping it would take others' requests with it."""
    not_found = {"jsonrpc": "2.0", "id": 0, "error": {"code": -32601, "message": "Method not found"}}
    assert not daemon._settings_differ(lambda params: not_found, ["--python-sandbox", "docker"])
    assert not daemon._settings_differ(lambda params: None, ["--python-sandbox", "docker"])


def test_only_a_request_that_names_settings_can_differ():
    assert not config_restart.settings_differ({}, ["--offline"])
    assert not config_restart.settings_differ(None, ["--offline"])
    assert not config_restart.settings_differ({"settings": ["--offline"]}, ["--offline"])
    assert config_restart.settings_differ({"settings": []}, ["--offline"])


def test_an_edit_made_while_the_daemon_was_starting_still_counts(monkeypatch, tmp_path):
    """The baseline is what the daemon was configured from, not what the watcher first sees."""
    monkeypatch.setattr(config_restart, "POLL_SECONDS", TICK)
    config = tmp_path / "config.yaml"
    config.write_text("pythonSandbox: conda\n")
    config_restart.remember(str(config))
    config.write_text("# edited while the session was being built\n")

    fired = threading.Event()
    monkeypatch.setattr(config_restart, "ConfigWatcher", _fast_watcher(fired))
    watcher = config_restart.watch(lambda: None, str(config))
    try:
        assert fired.wait(5)
    finally:
        watcher.stop()


def _fast_watcher(fired):
    original = ConfigWatcher

    def make(path, on_change, interval=None, baseline=None):
        def both():
            on_change()
            fired.set()

        return original(path, both, interval=TICK, baseline=baseline)

    return make
