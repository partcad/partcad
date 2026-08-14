#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc update`.

The command does two things that used to be one, and the order matters: PartCAD
itself is updated first, so a package that needs a newer PartCAD gets one. What
these pin down is the contract between the two halves -- which of them runs, in
which order, and which failures are allowed to stop the other.
"""

from collections.abc import Iterator

import partcad_cli.click.commands.update as update_command
import pytest
from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_utils import selfupdate
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
    """Record what the command does, without letting it reach a daemon or a network.

    Both halves are stubbed: `selfupdate` (which would talk to GitHub/PyPI and
    write to the installation) and `service.run` (which would start a daemon).
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

        def fake_run(self, cli_ctx, method, params=None, span_name=None, needs_context=False):
            self.events.append(("daemon", method))
            return {}

    rec = Recorder()
    monkeypatch.setattr(selfupdate, "update", rec.fake_update)
    monkeypatch.setattr(selfupdate, "check", rec.fake_check)
    monkeypatch.setattr(update_command, "run", rec.fake_run)
    return rec


def _invoke(click_runner, *args):
    return click_runner.invoke(cli, ["--no-ansi", "update", *args])


def test_update_updates_partcad_before_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None), ("daemon", "update")]


def test_partcad_only_skips_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only")
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None)]


def test_packages_only_skips_the_version_check(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--packages-only")
    assert result.exit_code == 0
    assert recorder.events == [("daemon", "update")]


def test_check_reports_without_installing_or_updating_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--check")
    assert result.exit_code == 0
    assert recorder.events == [("check", None)]
    assert "0.7.159 is available" in result.output


def test_check_says_so_when_up_to_date(click_runner: Iterator[CliRunner], recorder) -> None:
    recorder.check_result = {**recorder.check_result, "latest": "0.7.158", "update_available": False}
    result = _invoke(click_runner, "--check")
    assert "PartCAD 0.7.158 is up to date." in result.output


def test_to_version_is_passed_through(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only", "--to-version", "0.7.100")
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", "0.7.100")]


def test_partcad_only_and_packages_only_are_mutually_exclusive(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only", "--packages-only")
    assert result.exit_code == 2
    assert recorder.events == []


def test_packages_only_rejects_the_self_update_options(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--packages-only", "--check")
    assert result.exit_code == 2
    assert recorder.events == []


def test_a_failed_self_update_still_updates_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    """A source checkout, or an unreachable index, must not break `pc update`."""
    recorder.update_error = selfupdate.SelfUpdateError("PartCAD runs from a source checkout")
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None), ("daemon", "update")]
    assert "was not updated" in result.output


def test_a_failed_self_update_is_fatal_when_it_was_the_whole_request(
    click_runner: Iterator[CliRunner], recorder
) -> None:
    recorder.update_error = selfupdate.SelfUpdateError("could not reach https://pypi.org")
    result = _invoke(click_runner, "--partcad-only")
    assert result.exit_code == 1
    assert "could not reach" in result.output


def test_offline_skips_the_version_check_but_not_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    """`--offline` promises nothing is fetched, and a release lookup is a fetch."""
    result = click_runner.invoke(cli, ["--no-ansi", "--offline", "update"])
    assert result.exit_code == 0
    assert recorder.events == [("daemon", "update")]
    assert "Offline mode" in result.output


# ---------------------------------------------------------------------------
# The daemon half, which is the command's and not the updater's.
#
# `pc update` replaces the files its workspace's daemon is executing, so it stops
# that daemon and waits for it -- and only that one. Hunting for other
# workspaces' daemons would race every other client on this machine, and is
# unnecessary: the new version is installed beside the old, not over it.
# ---------------------------------------------------------------------------


def test_the_daemon_is_stopped_only_when_something_is_installed(
    click_runner: Iterator[CliRunner], recorder, monkeypatch
) -> None:
    from partcad_service_json_rpc import daemon

    stops = []
    monkeypatch.setattr(daemon, "stop_daemon", lambda *a, **kw: stops.append(kw) or True)

    _invoke(click_runner)
    assert stops == []  # nothing newer was found

    recorder.update_result = {**recorder.update_result, "updated": True}
    _invoke(click_runner)
    assert len(stops) == 1
    assert stops[0]["wait"] == daemon.STOP_TIMEOUT  # asked to stop *and* waited for


def test_update_installs_only_after_a_real_daemon_is_gone(click_runner: Iterator[CliRunner], monkeypatch) -> None:
    """The requirement, end to end: stop it, wait for it, *then* install.

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

    from partcad_service_json_rpc import daemon
    from partcad_service_json_rpc.core.session import Session
    from partcad_service_json_rpc.rpc.methods import build_registry
    from partcad_service_json_rpc.transport.socket_server import SocketServer
    from partcad_utils import selfupdate as real_selfupdate

    # A short HOME under /tmp keeps the AF_UNIX socket path under ~108 chars.
    home = tempfile.mkdtemp(prefix="pch", dir="/tmp")
    monkeypatch.setenv("HOME", home)
    root = daemon.determine_root_path()
    sock = daemon.socket_path(root)
    os.makedirs(os.path.dirname(sock), exist_ok=True)

    server = SocketServer(Session(), build_registry())
    threading.Thread(target=server.serve_unix, args=(sock,), daemon=True).start()
    for _ in range(500):
        if server._server_sock is not None:
            break
        time.sleep(0.01)

    observed = {}

    def install(version, repo, log):
        observed["alive_at_install"] = daemon.is_alive(sock)
        return "/installed/%s" % version

    monkeypatch.setattr(real_selfupdate, "installation_kind", lambda: real_selfupdate.KIND_STANDALONE)
    monkeypatch.setattr(real_selfupdate, "current_version", lambda: "0.7.158")
    monkeypatch.setattr(real_selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.159")
    monkeypatch.setattr(real_selfupdate, "_install_standalone", install)

    try:
        assert daemon.is_alive(sock) is True
        result = click_runner.invoke(cli, ["--no-ansi", "update", "--partcad-only"])
        assert result.exit_code == 0, result.output
        assert observed["alive_at_install"] is False
    finally:
        server.stop()
        shutil.rmtree(home, ignore_errors=True)
