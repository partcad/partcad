#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the executable entry point helpers."""

import pytest
from partcad_service_json_rpc import __main__ as m


def test_parse_args_defaults_to_stdio_and_info_verbosity():
    args = m.parse_args([])
    assert args.http is None
    assert args.verbose is False
    assert args.quiet is False


def test_http_flag_without_value_uses_the_default_address():
    args = m.parse_args(["--http"])
    assert args.http == m.DEFAULT_HTTP_ADDRESS


def test_http_flag_accepts_an_explicit_address():
    args = m.parse_args(["--http", "0.0.0.0:9000"])
    assert args.http == "0.0.0.0:9000"


def test_build_settings_maps_cli_flags_to_core_setting_keys():
    args = m.parse_args(["--verbose", "--offline", "--python-sandbox", "conda"])
    settings = m.build_settings(args)
    assert settings["verbosity"] == "debug"
    assert settings["offline"] == "true"
    assert settings["pythonSandbox"] == "conda"


def test_build_settings_quiet_sets_error_verbosity():
    assert m.build_settings(m.parse_args(["--quiet"]))["verbosity"] == "error"


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1:8017", ("127.0.0.1", 8017)),
        ("0.0.0.0:9000", ("0.0.0.0", 9000)),
        ("8080", ("127.0.0.1", 8080)),
    ],
)
def test_parse_host_port(address, expected):
    assert m.parse_host_port(address) == expected


# ---------------------------------------------------------------------------
# Updating the installation. The VS Code extension drives this, and parses the
# JSON report the last line carries, so both halves are contract.
# ---------------------------------------------------------------------------


def test_update_flags_are_off_by_default():
    args = m.parse_args([])
    assert args.self_update is False
    assert args.check_update is False
    assert args.update_to is None
    assert args.update_repository is None


def test_check_update_reports_and_prints_a_machine_readable_line(monkeypatch, capsys):
    import json

    from partcad_service_json_rpc import selfupdate

    status = {
        "kind": "standalone",
        "current": "0.7.158",
        "latest": "0.7.159",
        "pinned": None,
        "update_available": True,
        "reason": None,
    }
    monkeypatch.setattr(selfupdate, "check", lambda repo=None, to_version=None: status)
    assert m.main(["--check-update"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "0.7.159 is available" in out[0]
    assert json.loads(out[-1]) == status


def test_self_update_streams_progress_and_reports_the_result(monkeypatch, capsys):
    import json

    from partcad_service_json_rpc import selfupdate

    def fake_update(repo=None, to_version=None, log=None, **kwargs):
        log("Stopping 1 running PartCAD daemon(s) before installing...")
        return {"current": "0.7.158", "latest": "0.7.159", "updated": True, "reason": None}

    monkeypatch.setattr(selfupdate, "update", fake_update)
    assert m.main(["--self-update"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "Stopping 1 running PartCAD daemon(s)" in out[0]
    assert json.loads(out[-1])["updated"] is True


def test_self_update_reports_a_failure_on_stderr_and_exits_non_zero(monkeypatch, capsys):
    from partcad_service_json_rpc import selfupdate

    def fail(**kwargs):
        raise selfupdate.SelfUpdateError("checksum mismatch, the download is corrupted")

    monkeypatch.setattr(selfupdate, "update", fail)
    assert m.main(["--self-update"]) == 1
    assert "checksum mismatch" in capsys.readouterr().err


def test_update_flags_never_start_a_daemon(monkeypatch):
    """`--self-update` must exit before the service tries to serve anything."""
    from partcad_service_json_rpc import daemon, selfupdate

    def unexpected(*args, **kwargs):
        raise AssertionError("a daemon must not be started by an update")

    monkeypatch.setattr(daemon, "ensure_daemon", unexpected)
    monkeypatch.setattr(
        selfupdate,
        "check",
        lambda repo=None, to_version=None: {"current": "0.7.158", "reason": "a source checkout"},
    )
    assert m.main(["--check-update"]) == 0
