#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Handing a resolved user configuration to another process.

A PartCAD client resolves its own configuration -- a config file, the ``PC_*``
environment and the command line, layered -- and then asks the daemon to do the
work. The daemon has a configuration of its own, resolved from whatever
environment happened to start it and warm ever since, so it says nothing about
how the command being served was invoked. ``to_dict``/``from_dict`` is what lets
the caller's configuration be the one the work is done under.

The test that matters is therefore not "the dict has the right keys" but "a
process whose own configuration says the opposite ends up with the caller's
values", which is what the round trip below sets up: two different HOMEs, with
opposing config files.
"""

import json

import pytest

from partcad_utils.user_config import OPTION_KEYS, UserConfig

CLIENT_CONFIG = """
forceUpdate: true
develIndex: true
offline: true
threadsMax: 3
pythonSandbox: pypy
cacheFiles: false
logLevel: error
git:
  clone:
    timeout: 42
  auth:
    github.com:
      username: alice
      password: secret-token
  config:
    http.proxy: http://proxy:3128
telemetry:
  type: none
parameters:
  obj1:
    k: v
"""

# The same options, set the other way round, so nothing can pass by accident.
DAEMON_CONFIG = """
forceUpdate: false
develIndex: false
offline: false
threadsMax: 9
pythonSandbox: none
cacheFiles: true
logLevel: debug
"""


def config_at(tmp_path, name, text):
    home = tmp_path / name
    (home / ".partcad").mkdir(parents=True)
    (home / ".partcad" / "config.yaml").write_text(text)
    return home


# What CI exports for every job (see the workflow's top-level 'env'). These are
# the reason this file sets the environment at all: reading a 'telemetry' key
# while one of them is set used to raise KeyError out of vyper, so a copy taken
# under CI's environment failed where a copy taken under a bare one passed.
CI_TELEMETRY_ENV = {"PC_TELEMETRY_ENV": "test", "PC_TELEMETRY_PERFORMANCE": "false"}


@pytest.fixture(params=[{}, CI_TELEMETRY_ENV], ids=["bare-environment", "ci-environment"])
def homes(request, tmp_path, monkeypatch):
    """A client and a daemon whose configurations disagree about everything.

    Run twice: once under a bare environment and once under the one CI exports,
    because the two used to disagree about whether taking a copy works at all.
    """
    # Cleared first, or the bare case is only bare when the suite happens to be
    # run outside CI -- which is exactly the blind spot this parametrization
    # exists to close, and it would close it in one direction only.
    for name in CI_TELEMETRY_ENV:
        monkeypatch.delenv(name, raising=False)

    client_home = config_at(tmp_path, "client", CLIENT_CONFIG)
    daemon_home = config_at(tmp_path, "daemon", DAEMON_CONFIG)
    for name, value in request.param.items():
        monkeypatch.setenv(name, value)

    def build(home, settings=None):
        monkeypatch.setenv("HOME", str(home))
        return UserConfig(settings=settings)

    return build, client_home, daemon_home


# ---- the copy itself ---------------------------------------------------------


def test_the_copy_is_json_serializable(homes):
    """It travels as JSON-RPC parameters, so it has to survive the trip."""
    build, client_home, _ = homes
    data = build(client_home).to_dict()
    assert json.loads(json.dumps(data)) == data


def test_every_option_travels(homes):
    """A missing key means the daemon silently resolves that option itself."""
    build, client_home, _ = homes
    data = build(client_home).to_dict()
    for key in OPTION_KEYS:
        assert key in data, "%s never reaches the daemon" % key


def test_an_unset_option_is_left_out_rather_than_sent_as_null(tmp_path, monkeypatch):
    """Sending null would override the option with an empty value instead of
    letting it fall back to the same default. 'threadsMax' is the one that shows
    it: it resolves to None unless set, and 0 threads is not a default."""
    monkeypatch.delenv("PC_THREADS_MAX", raising=False)
    monkeypatch.setenv("HOME", str(config_at(tmp_path, "empty", "")))

    data = UserConfig().to_dict()

    assert "threadsMax" not in data
    assert UserConfig(settings=data).threads_max is None


# ---- the round trip ----------------------------------------------------------


@pytest.mark.parametrize(
    "attribute,expected",
    [
        ("force_update", True),
        ("devel_index", True),
        ("offline", True),
        ("threads_max", 3),
        ("python_sandbox", "pypy"),
        ("cache", False),
        ("log_level", "error"),
        ("git_clone_timeout", 42),
    ],
)
def test_the_caller_s_options_win_over_the_rebuilding_process_own(homes, attribute, expected):
    build, client_home, daemon_home = homes
    data = build(client_home).to_dict()

    rebuilt = build(daemon_home, settings=data)

    assert getattr(rebuilt, attribute) == expected


def test_the_rebuilding_process_own_configuration_really_does_disagree(homes):
    """Guards the test above: if both HOMEs agreed it would prove nothing."""
    build, _client, daemon_home = homes
    own = build(daemon_home)
    assert own.force_update is False
    assert own.devel_index is False
    assert own.threads_max == 9


def test_the_nested_sections_travel_too(homes):
    """git.auth is what lets the daemon clone a caller's private dependency;
    git.config carries the proxy the transfer has to go through."""
    build, client_home, daemon_home = homes
    data = build(client_home).to_dict()

    rebuilt = build(daemon_home, settings=data)

    assert rebuilt.git_auth.to_dict() == {"github.com": {"username": "alice", "password": "secret-token"}}
    assert rebuilt.git_config.to_dict() == {"http.proxy": "http://proxy:3128"}
    assert rebuilt.parameter_config.to_dict() == {"obj1": {"k": "v"}}


def test_a_nested_section_does_not_clobber_the_flat_key_beside_it(homes):
    """'git.clone.timeout' lives under the same 'git' root as 'git.auth' and
    'git.config'; applying one must not take the others down with it."""
    build, client_home, daemon_home = homes
    data = build(client_home).to_dict()

    rebuilt = build(daemon_home, settings=data)

    assert rebuilt.git_clone_timeout == 42
    assert rebuilt.git_auth.to_dict() != {}


def test_the_copy_round_trips_unchanged(homes):
    """Rebuilding and re-serializing has to be a fixed point, or a context that
    is rebuilt from its own fingerprint would look like a different one."""
    build, client_home, daemon_home = homes
    data = build(client_home).to_dict()

    assert build(daemon_home, settings=data).to_dict() == data


def test_no_settings_means_the_process_reads_its_own_configuration(homes):
    """The plain constructor has to keep behaving exactly as it did."""
    build, client_home, _ = homes
    assert build(client_home).force_update is True


def test_the_environment_does_not_outrank_a_handed_over_configuration(homes, monkeypatch):
    """The daemon inherits the environment of whatever started it; the caller's
    configuration has to win over that too, not just over the config file."""
    build, client_home, daemon_home = homes
    data = build(client_home).to_dict()
    monkeypatch.setenv("PC_DEVEL_INDEX", "0")
    monkeypatch.setenv("PC_FORCE_UPDATE", "0")

    rebuilt = build(daemon_home, settings=data)

    assert rebuilt.devel_index is True
    assert rebuilt.force_update is True


# ---- what must not travel ----------------------------------------------------


def test_telemetry_does_not_travel(homes):
    """Telemetry belongs to a process, not to a package.

    It is initialized once at import, long before any context exists, and
    nothing in context creation reads it -- so copying it would be inert, and a
    daemon reporting under the caller's DSN and environment would be wrong even
    if it were not.
    """
    build, client_home, _ = homes
    assert not [key for key in build(client_home).to_dict() if key.startswith("telemetry")]


def telemetry_of(config):
    """The telemetry settings a configuration resolves to."""
    telemetry = config.telemetry_config
    return {
        name: getattr(telemetry, name)
        for name in ("type", "env", "performance", "failures", "debug", "sentry_attach_stacktrace")
    }


def test_the_rebuilt_configuration_keeps_its_own_telemetry(homes):
    """Not just "it did not adopt the client's 'none'" -- the whole telemetry
    configuration has to be the one this process resolved for itself, which only
    a comparison against that baseline can show."""
    build, client_home, daemon_home = homes
    baseline = telemetry_of(build(daemon_home))
    data = build(client_home).to_dict()

    rebuilt = build(daemon_home, settings=data)

    assert telemetry_of(rebuilt) == baseline
