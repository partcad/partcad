#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login': what reaches the daemon, what opens on this machine, and what is saved.

The daemon is a recorder and the browser a stand-in that reports at once; the
loop, the listener and the configuration file are the real ones.
"""

import threading
import urllib.parse
import urllib.request

import yaml
from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands import login as login_command
from partcad_client import browser as pc_browser
from partcad_client import login as pc_login

SPEC = {"url": "https://example.com/login", "title": "Example", "capture": [{"name": "t"}], "timeout": 30}


class _Daemon:
    """'plugin.login' as the daemon answers it: the browser once, then done with what it brought."""

    def __init__(self, ask_for_browser=True):
        self.calls = []
        self.ask_for_browser = ask_for_browser

    def run(self, cli_ctx, method, params, needs_context=False):
        self.calls.append((method, params, needs_context))
        if params.get("values"):
            return {"plugin": "//p:repo", "status": "done", "parameters": {"token": params["values"]["t"]}}
        if self.ask_for_browser and not params["browser"]:
            if params["check"]:
                return {"plugin": "//p:repo", "status": "failed", "message": "logging in needs the browser"}
            if params["non_interactive"]:
                return {"plugin": "//p:repo", "status": "instructions", "spec": dict(SPEC, instructions="Or a key.")}
            return {"plugin": "//p:repo", "status": "browser", "spec": SPEC}
        token = params["browser"][0]["t"] if params["browser"] else "kept"
        return {"plugin": "//p:repo", "status": "done", "parameters": {"token": token}, "message": "Logged in as ann"}


class _Opened:
    browser = "Test Browser"
    note = ""

    def close(self):
        pass


def _browser_that_reports(values, opened):
    def open_browser(url, chosen):
        done = url.replace("/start", "/done") + "?" + urllib.parse.urlencode(values)
        threading.Thread(target=lambda: urllib.request.urlopen(done, timeout=10).read(), daemon=True).start()
        opened.append(url)
        return _Opened()

    return open_browser


def _setup(monkeypatch, tmp_path, daemon):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(login_command, "run", daemon.run)
    monkeypatch.setattr(pc_login.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pc_browser, "choose", lambda name=None: pc_browser.Browser("chrome", ["/bin/chrome"]))


def test_pc_login_opens_the_browser_and_saves_what_it_brought(monkeypatch, tmp_path):
    daemon = _Daemon()
    _setup(monkeypatch, tmp_path, daemon)
    opened = []
    monkeypatch.setattr(pc_browser, "open_browser", _browser_that_reports({"t": "abc"}, opened))

    result = CliRunner().invoke(cli, ["--no-ansi", "login", "//p:repo"])

    assert result.exit_code == 0, result.output
    assert [call[0] for call in daemon.calls] == ["plugin.login", "plugin.login"]
    assert daemon.calls[0][1] == {"plugin": "//p:repo", "browser": [], "check": False, "non_interactive": False}
    assert daemon.calls[1][1]["browser"] == [{"t": "abc"}]
    assert all(call[2] for call in daemon.calls)  # the plugin is resolved in the workspace's context
    assert opened[0].startswith("http://127.0.0.1:") and opened[0].endswith("/start")
    saved = yaml.safe_load((tmp_path / ".partcad" / "config.yaml").read_text())
    assert saved == {"parameters": {"//p:repo": {"token": "abc"}}}
    assert "Logged in as ann" in result.output


def test_pc_login_check_never_opens_the_browser_and_fails_when_one_is_needed(monkeypatch, tmp_path):
    daemon = _Daemon()
    _setup(monkeypatch, tmp_path, daemon)
    monkeypatch.setattr(pc_browser, "open_browser", lambda url, chosen: (_ for _ in ()).throw(AssertionError(url)))

    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--check", "//p:repo"])

    assert result.exit_code != 0
    assert "logging in needs the browser" in result.output
    assert daemon.calls[0][1]["check"] is True
    assert not (tmp_path / ".partcad" / "config.yaml").exists()


def test_pc_login_check_of_working_credentials_saves_nothing(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _Daemon(ask_for_browser=False))
    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--check", "//p:repo"])
    assert result.exit_code == 0 and "Logged in as ann" in result.output
    assert not (tmp_path / ".partcad" / "config.yaml").exists()


def _no_browser(monkeypatch):
    def fail(*args):
        raise AssertionError("a browser was looked for or opened")

    monkeypatch.setattr(pc_browser, "open_browser", fail)
    monkeypatch.setattr(pc_browser, "choose", fail)


def test_pc_login_agent_prints_what_to_do_and_opens_nothing(monkeypatch, tmp_path):
    daemon = _Daemon()
    _setup(monkeypatch, tmp_path, daemon)
    _no_browser(monkeypatch)

    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--agent", "//p:repo"])

    assert result.exit_code == login_command.INSTRUCTIONS_EXIT_CODE, result.output
    assert daemon.calls[0][1]["non_interactive"] is True
    assert "https://example.com/login" in result.output
    assert "Or a key." in result.output
    assert "pc login --agent //p:repo --set t=<t>" in result.output
    assert not (tmp_path / ".partcad" / "config.yaml").exists()


def test_non_interactive_is_agent_and_interactive_turns_it_back(monkeypatch, tmp_path):
    daemon = _Daemon()
    _setup(monkeypatch, tmp_path, daemon)
    _no_browser(monkeypatch)
    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--non-interactive", "//p:repo"])
    assert result.exit_code == login_command.INSTRUCTIONS_EXIT_CODE
    monkeypatch.setattr(pc_browser, "choose", lambda name=None: pc_browser.Browser("chrome", ["/bin/chrome"]))
    monkeypatch.setattr(pc_browser, "open_browser", _browser_that_reports({"t": "abc"}, []))
    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--agent", "--interactive", "//p:repo"])
    assert result.exit_code == 0, result.output
    assert daemon.calls[-2][1]["non_interactive"] is False


def test_pc_login_set_hands_the_values_over_and_saves_what_the_plugin_took(monkeypatch, tmp_path):
    daemon = _Daemon()
    _setup(monkeypatch, tmp_path, daemon)
    _no_browser(monkeypatch)

    result = CliRunner().invoke(cli, ["--no-ansi", "login", "--agent", "--set", "t=a=b", "//p:repo"])

    assert result.exit_code == 0, result.output
    assert daemon.calls[0][1]["values"] == {"t": "a=b"}
    saved = yaml.safe_load((tmp_path / ".partcad" / "config.yaml").read_text())
    assert saved == {"parameters": {"//p:repo": {"token": "a=b"}}}


def test_pc_login_refuses_what_it_cannot_mean(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _Daemon())
    assert CliRunner().invoke(cli, ["--no-ansi", "login", "--set", "novalue", "//p:repo"]).exit_code == 2
    assert CliRunner().invoke(cli, ["--no-ansi", "login", "--agent", "--manual", "//p:repo"]).exit_code == 2
