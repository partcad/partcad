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
