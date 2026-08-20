#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc upgrade`.

`pc upgrade` replaces this machine's copy of PartCAD; `pc update` refetches a
package's imports. They are separate commands on opposite sides of the command
boundary, and the first thing checked here is that they stay that way: an upgrade
must not touch the package graph, and must not need a daemon to do its job --
beyond stopping the ones that are executing the files it replaces.
"""

from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_client_utils import selfupdate
from partcad_utils.user_config import user_config


@pytest.fixture(autouse=True)
def clean_user_config(monkeypatch):
    """Undo the global options a previous `cli` invocation left behind.

    `command.py` writes the parsed globals onto the process-wide `user_config`
    singleton, so one `--offline` run would otherwise make every test after it
    skip the version check.
    """
    monkeypatch.setattr(user_config, "offline", False, raising=False)


@pytest.fixture
def recorder(monkeypatch):
    """Record what the command does, without letting it reach a network.

    `selfupdate` is stubbed, since the real one would talk to GitHub/PyPI and
    write to the installation.
    """

    class Recorder:
        def __init__(self):
            self.events = []
            self.update_result = {"updated": False, "current": "0.7.158", "latest": "0.7.158", "reason": None}
            self.check_result = {
                "kind": "standalone",
                "current": "0.7.158",
                "latest": "0.7.159",
                "pinned": None,
                "update_available": True,
                "reason": None,
            }
            self.update_error = None

        def fake_update(self, to_version=None, log=None, before_install=None, **kwargs):
            # Run the hook the way the real `update` does -- once something newer
            # is confirmed -- so the command's daemon stop is exercised here too.
            self.events.append(("selfupdate", to_version))
            if self.update_error:
                raise self.update_error
            if before_install is not None and self.update_result.get("updated"):
                before_install()
            return self.update_result

        def fake_check(self, to_version=None, **kwargs):
            self.events.append(("check", to_version))
            if self.update_error:
                raise self.update_error
            return self.check_result

    rec = Recorder()
    monkeypatch.setattr(selfupdate, "update", rec.fake_update)
    monkeypatch.setattr(selfupdate, "check", rec.fake_check)
    return rec


def _invoke(click_runner, *args):
    return click_runner.invoke(cli, ["--no-ansi", "upgrade", *args])


def test_upgrade_upgrades_partcad(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None)]


def test_upgrade_never_touches_the_package_graph(click_runner: Iterator[CliRunner], recorder, monkeypatch) -> None:
    """The reason this is not a flag on `pc update`: it is not that command.

    Refetching a package's imports is `pc update`, a thin daemon client. An
    upgrade acts on the machine, so it must not open a context, load a package,
    or send anything to a daemon beyond `daemon.stop`.
    """
    from partcad_cli.click import service

    def unexpected(*args, **kwargs):
        raise AssertionError("`pc upgrade` must not call the daemon")

    monkeypatch.setattr(service, "run", unexpected)
    recorder.update_result = {**recorder.update_result, "updated": True}
    assert _invoke(click_runner).exit_code == 0


def test_check_reports_without_installing(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--check")
    assert result.exit_code == 0
    assert recorder.events == [("check", None)]
    assert "0.7.159 is available" in result.output
    assert "Run `pc upgrade` to install it" in result.output


def test_check_says_so_when_up_to_date(click_runner: Iterator[CliRunner], recorder) -> None:
    recorder.check_result = {**recorder.check_result, "latest": "0.7.158", "update_available": False}
    result = _invoke(click_runner, "--check")
    assert "PartCAD 0.7.158 is up to date." in result.output


def test_to_version_is_passed_through(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--to-version", "0.7.100")
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", "0.7.100")]


def test_a_failed_upgrade_is_fatal(click_runner: Iterator[CliRunner], recorder) -> None:
    """Upgrading is the whole request, so failing it fails the command."""
    recorder.update_error = selfupdate.SelfUpdateError("could not reach https://pypi.org")
    result = _invoke(click_runner)
    assert result.exit_code == 1
    assert "could not reach" in result.output


def test_a_source_checkout_is_reported(click_runner: Iterator[CliRunner], recorder) -> None:
    recorder.update_error = selfupdate.SelfUpdateError("PartCAD runs from a source checkout")
    result = _invoke(click_runner)
    assert result.exit_code == 1
    assert "source checkout" in result.output


def test_offline_skips_the_version_check(click_runner: Iterator[CliRunner], recorder) -> None:
    """`--offline` promises nothing is fetched, and a release lookup is a fetch."""
    result = click_runner.invoke(cli, ["--no-ansi", "--offline", "upgrade"])
    assert result.exit_code == 0
    assert recorder.events == []
    assert "Offline mode" in result.output


# ---------------------------------------------------------------------------
# The daemon half, which is the command's and not the upgrader's.
#
# Every daemon on this machine executes the files `pc upgrade` replaces, so it
# stops all of them and waits. Doing that from a client is what keeps it simple:
# one process acting on its own machine, rather than daemons policing each other.
# ---------------------------------------------------------------------------


def test_the_daemons_are_stopped_only_when_something_is_installed(
    click_runner: Iterator[CliRunner], recorder, monkeypatch
) -> None:
    from partcad_client_utils import daemon

    calls = []
    monkeypatch.setattr(daemon, "live_daemon_dirs", lambda *a, **kw: ["/tmp/ws-a", "/tmp/ws-b"])
    monkeypatch.setattr(daemon, "stop_all_daemons", lambda *a, **kw: calls.append(True) or ["/tmp/ws-a", "/tmp/ws-b"])

    _invoke(click_runner)
    assert calls == []  # nothing newer was found

    recorder.update_result = {**recorder.update_result, "updated": True}
    result = _invoke(click_runner)
    assert calls == [True]
    assert "Stopping 2 running PartCAD daemon(s)" in result.output


def test_a_daemon_that_will_not_stop_is_reported_not_fatal(
    click_runner: Iterator[CliRunner], recorder, monkeypatch
) -> None:
    """Side-by-side install is what makes a survivor survivable; say so and go on."""
    from partcad_client_utils import daemon

    monkeypatch.setattr(daemon, "live_daemon_dirs", lambda *a, **kw: ["/tmp/ws-a", "/tmp/ws-b"])
    monkeypatch.setattr(daemon, "stop_all_daemons", lambda *a, **kw: ["/tmp/ws-a"])

    recorder.update_result = {**recorder.update_result, "updated": True}
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert "1 PartCAD daemon(s) did not stop" in result.output


def test_upgrade_installs_only_after_the_real_daemons_are_gone(click_runner: Iterator[CliRunner], monkeypatch) -> None:
    """The requirement, end to end: stop them, wait, *then* install.

    A real daemon is started and the installer is stubbed to record, at the
    moment it runs, whether anything still answers on the socket.
    """
    import os
    import shutil
    import socket as socket_module
    import tempfile
    import threading
    import time

    if not hasattr(socket_module, "AF_UNIX"):
        pytest.skip("AF_UNIX not available on this platform")

    from partcad_client_utils import daemon
    from partcad_client_utils import selfupdate as real_selfupdate
    from partcad_service_json_rpc.core.session import Session
    from partcad_service_json_rpc.rpc.methods import build_registry
    from partcad_service_json_rpc.transport.socket_server import SocketServer

    # A short HOME under /tmp keeps the AF_UNIX socket path under ~108 chars.
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    # Two workspaces, so "all local daemons" is more than "this one".
    socks = []
    servers = []
    for name in ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"):
        wdir = os.path.join(daemon.workspaces_dir(), name)
        os.makedirs(wdir, exist_ok=True)
        sock = os.path.join(wdir, "socket")
        server = SocketServer(Session(), build_registry())
        threading.Thread(target=server.serve_unix, args=(sock,), daemon=True).start()
        for _ in range(500):
            if server._server_sock is not None:
                break
            time.sleep(0.01)
        socks.append(sock)
        servers.append(server)

    observed = {}

    def install(version, repo, log):
        observed["alive_at_install"] = [s for s in socks if daemon.is_alive(s)]
        return "/installed/%s" % version

    monkeypatch.setattr(real_selfupdate, "installation_kind", lambda: real_selfupdate.KIND_STANDALONE)
    monkeypatch.setattr(real_selfupdate, "current_version", lambda: "0.7.158")
    monkeypatch.setattr(real_selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.159")
    monkeypatch.setattr(real_selfupdate, "_install_standalone", install)

    try:
        assert all(daemon.is_alive(s) for s in socks)
        result = click_runner.invoke(cli, ["--no-ansi", "upgrade"])
        assert result.exit_code == 0, result.output
        assert observed["alive_at_install"] == []
    finally:
        for server in servers:
            server.stop()
        shutil.rmtree(home, ignore_errors=True)
