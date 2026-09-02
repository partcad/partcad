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


def test_devel_index_is_off_unless_asked_for():
    assert "develIndex" not in m.build_settings(m.parse_args([]))


def test_devel_index_reaches_the_session_settings():
    assert m.build_settings(m.parse_args(["--devel-index"]))["develIndex"] == "true"


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


# What `settings_argv` must *not* repeat: the channel is what its caller
# replaces, and `--help`/`--version` never reach a daemon at all.
CHANNEL_OPTIONS = {"help", "version", "socket", "stdio", "http", "serve_pipe"}


def _every_setting_flag() -> list:
    """Every non-channel option the service takes, each with a non-default value.

    Read off the parser rather than listed here on purpose: a setting added to
    the service is then a setting this test starts checking, which is the whole
    point -- one that `settings_argv` forgets is one the Windows daemon takes
    the default for, silently, and no suite starts a real one to notice.

    ``_actions`` is private, and argparse offers nothing public that enumerates
    a parser's options.
    """
    argv = []
    for action in m.build_parser()._actions:
        if action.dest in CHANNEL_OPTIONS:
            continue
        argv.append(action.option_strings[-1])
        if action.nargs != 0:  # takes a value; store_true actions take none
            argv.append("a-" + action.dest.replace("_", "-"))
    return argv


def test_settings_argv_round_trips_through_the_parser():
    # The daemon this argv starts has to behave like the launcher was told to.
    args = m.parse_args(["--verbose", "--offline", "--python-sandbox", "conda"])
    assert m.settings_argv(args) == ["--verbose", "--offline", "--python-sandbox", "conda"]
    assert m.build_settings(m.parse_args(m.settings_argv(args))) == m.build_settings(args)


def test_settings_argv_carries_every_setting_the_service_takes():
    args = m.parse_args(_every_setting_flag())
    assert m.build_settings(m.parse_args(m.settings_argv(args))) == m.build_settings(args)


def test_settings_argv_of_a_default_launcher_is_empty():
    # Nothing was asked for, so nothing is passed on -- the daemon is spawned
    # with the same argv it always was.
    assert m.settings_argv(m.parse_args([])) == []
