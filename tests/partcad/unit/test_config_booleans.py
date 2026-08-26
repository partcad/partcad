#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a boolean option written as text is read.

Every boolean user-configuration option is bound to a ``PC_*`` environment
variable, and an environment variable can only carry a string. vyper's own
``get_bool`` treats every string but "false" as true, so ``PC_FORCE_UPDATE=0``
used to turn the flag *on* -- and, worse, ``pc`` disagreed with the daemon it
launches about the very same variable, because click converts it with its own
BOOL type. ``UserConfig.get_bool`` now makes that conversion once, for every
option, so the two halves cannot drift apart again.

These tests build a fresh ``UserConfig`` per case rather than reading the
process-wide singleton: it is constructed at import time, so it has already read
the environment this test wants to change.
"""

import pytest

from partcad_utils.booleans import to_bool
from partcad_utils.user_config import UserConfig

# The falsy spellings that used to read as true. "" is here because an
# environment variable set to nothing means the flag is not on.
FALSE_TEXT = ["0", "false", "False", "FALSE", "no", "n", "off", "f", "", "  ", " off "]
TRUE_TEXT = ["1", "true", "True", "TRUE", "yes", "y", "on", "t", " on "]

# option key -> (environment variable, attribute on UserConfig). Every boolean
# option that is bound to one, so a new one cannot quietly be added with the old
# reading.
BOOLEAN_OPTIONS = [
    ("develIndex", "PC_DEVEL_INDEX", "devel_index"),
    ("forceUpdate", "PC_FORCE_UPDATE", "force_update"),
    ("offline", "PC_OFFLINE", "offline"),
    ("cacheMem", "PC_CACHE_MEM", "cache_memory"),
    ("cacheFiles", "PC_CACHE_FILES", "cache"),
    ("cacheRemote", "PC_CACHE_REMOTE", "cache_remote"),
    ("cacheS3", "PC_CACHE_S3", "cache_s3"),
    ("cacheDependenciesIgnore", "PC_CACHE_DEPENDENCIES_IGNORE", "cache_dependencies_ignore"),
    ("ignoreBundledOpenscad", "IGNORE_BUNDLED_OPENSCAD", "ignore_bundled_openscad"),
]

# The boolean options with no environment binding, settable in config.yaml only.
# They read through the same get_bool, so they are covered there instead.
CONFIG_ONLY_OPTIONS = [
    ("useDocker", "use_docker"),
    ("useDockerPython", "use_docker_python_declared"),
    ("useDockerKicad", "use_docker_kicad_declared"),
]

# The booleans TelemetryConfig reads, which go through the same get_bool.
TELEMETRY_OPTIONS = [
    ("PC_TELEMETRY_PERFORMANCE", "performance"),
    ("PC_TELEMETRY_FAILURES", "failures"),
    ("PC_TELEMETRY_DEBUG", "debug"),
    ("PC_TELEMETRY_SENTRY_ATTACH_STACKTRACE", "sentry_attach_stacktrace"),
]


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """An empty user configuration, so only the environment is in play."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def build_config(monkeypatch, env_var=None, value=None):
    for _key, variable, _attribute in BOOLEAN_OPTIONS:
        monkeypatch.delenv(variable, raising=False)
    for variable, _attribute in TELEMETRY_OPTIONS:
        monkeypatch.delenv(variable, raising=False)
    if env_var is not None:
        monkeypatch.setenv(env_var, value)
    return UserConfig()


# ---- to_bool ----------------------------------------------------------------


@pytest.mark.parametrize("text", FALSE_TEXT)
def test_falsy_text_reads_as_false(text):
    assert to_bool(text) is False


@pytest.mark.parametrize("text", TRUE_TEXT)
def test_truthy_text_reads_as_true(text):
    assert to_bool(text) is True


@pytest.mark.parametrize("value,expected", [(True, True), (False, False), (0, False), (1, True), (2, True)])
def test_values_that_are_already_boolean_or_numeric_are_taken_as_they_are(value, expected):
    """A YAML configuration file produces these rather than strings."""
    assert to_bool(value) is expected


def test_an_absent_value_falls_back_to_the_default():
    assert to_bool(None) is False
    assert to_bool(None, default=True) is True


def test_an_unrecognized_value_stays_on_the_side_it_was_always_on():
    """Only the falsy spellings change meaning; a typo reads as before.

    'bool(str)' was true for every non-empty string, so keeping an unknown value
    true means this reading can only ever change the answer for a value that was
    meant to be false.
    """
    assert to_bool("maybe") is True


# ---- every boolean option, read from the environment ------------------------


@pytest.mark.parametrize("key,env_var,attribute", BOOLEAN_OPTIONS, ids=[o[0] for o in BOOLEAN_OPTIONS])
@pytest.mark.parametrize("text", ["0", "no", "off", "false"])
def test_every_boolean_option_can_be_turned_off_from_the_environment(
    config_home, monkeypatch, key, env_var, attribute, text
):
    config = build_config(monkeypatch, env_var, text)
    assert getattr(config, attribute) is False, "%s=%s did not turn %s off" % (env_var, text, key)


@pytest.mark.parametrize("key,env_var,attribute", BOOLEAN_OPTIONS, ids=[o[0] for o in BOOLEAN_OPTIONS])
@pytest.mark.parametrize("text", ["1", "yes", "on", "true"])
def test_every_boolean_option_can_be_turned_on_from_the_environment(
    config_home, monkeypatch, key, env_var, attribute, text
):
    config = build_config(monkeypatch, env_var, text)
    assert getattr(config, attribute) is True, "%s=%s did not turn %s on" % (env_var, text, key)


@pytest.mark.parametrize("env_var,attribute", TELEMETRY_OPTIONS, ids=[o[1] for o in TELEMETRY_OPTIONS])
def test_the_telemetry_booleans_read_the_same_way(config_home, monkeypatch, env_var, attribute):
    """TelemetryConfig reads through the same object, so it must agree."""
    assert getattr(build_config(monkeypatch, env_var, "0").telemetry_config, attribute) is False
    assert getattr(build_config(monkeypatch, env_var, "1").telemetry_config, attribute) is True


# ---- the same reading, from the configuration file ---------------------------


@pytest.mark.parametrize(
    "key,attribute",
    [(key, attribute) for key, _env, attribute in BOOLEAN_OPTIONS] + CONFIG_ONLY_OPTIONS,
)
@pytest.mark.parametrize("written,expected", [("false", False), ("0", False), ("true", True), ("1", True)])
def test_config_file_values_read_the_same_way(config_home, monkeypatch, key, attribute, written, expected):
    """YAML hands over real booleans and integers rather than strings, and the
    options with no environment binding are only reachable this way."""
    (config_home / ".partcad").mkdir(exist_ok=True)
    (config_home / ".partcad" / "config.yaml").write_text("%s: %s\n" % (key, written))
    assert getattr(build_config(monkeypatch), attribute) is expected


# ---- defaults ----------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute,expected",
    [
        ("cache", True),
        ("cache_memory", True),
        ("cache_remote", False),
        ("cache_s3", False),
        ("use_docker", True),
        ("use_docker_kicad", True),
        ("use_docker_kicad_declared", True),
        ("use_docker_python", False),
        ("use_docker_python_declared", False),
        ("force_update", False),
        ("devel_index", False),
        ("offline", False),
        ("cache_dependencies_ignore", False),
        ("ignore_bundled_openscad", False),
    ],
)
def test_an_option_nobody_set_keeps_its_default(config_home, monkeypatch, attribute, expected):
    """The reading changed; what an unset option means did not."""
    assert getattr(build_config(monkeypatch), attribute) is expected


# ---- the master switch -------------------------------------------------------


@pytest.mark.parametrize(
    "declared_option,declared_attribute,effective_attribute",
    [
        ("useDockerPython", "use_docker_python_declared", "use_docker_python"),
        ("useDockerKicad", "use_docker_kicad_declared", "use_docker_kicad"),
    ],
)
def test_use_docker_off_turns_off_what_it_governs(
    config_home, monkeypatch, declared_option, declared_attribute, effective_attribute
):
    """'useDocker: false' is how a machine with no Docker says so once, rather
    than once per subject. What each option was *set* to is still readable, and
    is what the tags report, so a package can tell the two apart."""
    (config_home / ".partcad").mkdir(exist_ok=True)
    (config_home / ".partcad" / "config.yaml").write_text("useDocker: false\n%s: true\n" % declared_option)

    config = build_config(monkeypatch)
    assert getattr(config, declared_attribute) is True
    assert getattr(config, effective_attribute) is False


def test_use_docker_on_leaves_each_option_to_itself(config_home, monkeypatch):
    (config_home / ".partcad").mkdir(exist_ok=True)
    (config_home / ".partcad" / "config.yaml").write_text("useDocker: true\nuseDockerPython: true\n")

    config = build_config(monkeypatch)
    assert config.use_docker_python is True
    assert config.use_docker_kicad is True  # its own default


# ---- the option that was bound but never read --------------------------------


def test_offline_is_actually_read_from_the_environment(config_home, monkeypatch):
    """'PC_OFFLINE' was bound to a key nothing looked up, so it did nothing.

    The default was assigned before the binding rather than read after it, which
    left the variable inert everywhere except the CLI, where '--offline' sets
    the attribute directly.
    """
    assert build_config(monkeypatch, "PC_OFFLINE", "1").offline is True
