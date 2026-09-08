#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which sandbox gets used when nobody has said which.

Two questions, and they are different: what the configuration works out at
startup, and what a context does with that the first time it actually needs a
sandbox. The second is where the container runtime is asked about, because
asking means talking to a daemon and a command that never builds a sandbox
should not pay for it.
"""

import types

import pytest

from partcad import context as pc_context
from partcad import runtime
from partcad_utils.user_config import UserConfig


class _Ctx:
    """A context reduced to what choosing a sandbox reads."""

    def __init__(self, user_config):
        self.user_config = user_config
        self.use_docker_python_warned = False

    preferred_python_sandbox = pc_context.Context.preferred_python_sandbox


def _config(**overrides):
    made = UserConfig()
    made.use_docker = overrides.pop("use_docker", True)
    made.use_docker_python_declared = overrides.pop("use_docker_python_declared", False)
    for key, value in overrides.items():
        setattr(made, key, value)
    return made


# --------------------------------------------------------------------------- #
# Nobody said                                                                  #
# --------------------------------------------------------------------------- #


def test_a_container_runtime_wins_when_nothing_was_declared(monkeypatch):
    """What conda provisions depends on the host; what an image carries does not."""
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    assert _Ctx(_config()).preferred_python_sandbox() == "docker"


def test_without_a_container_runtime_the_startup_default_stands(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    config = _config()
    assert _Ctx(config).preferred_python_sandbox() == config.python_sandbox
    assert config.python_sandbox in ("conda", "venv")


def test_the_master_switch_is_honoured(monkeypatch):
    """'useDocker: false' is a machine saying it does not do containers."""
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    config = _config(use_docker=False)
    assert _Ctx(config).preferred_python_sandbox() == config.python_sandbox


# --------------------------------------------------------------------------- #
# Somebody said                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stated", ["conda", "venv", "none", "pypy"])
def test_a_stated_preference_is_obeyed(monkeypatch, stated):
    """A machine with Docker running is not a machine that wants to render in it."""
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    config = _config()
    config.python_sandbox = stated
    assert _Ctx(config).preferred_python_sandbox() == stated


def test_setting_it_is_what_makes_it_stated():
    """'--python-sandbox' arrives as an assignment after the configuration is read."""
    config = _config()
    assert config.python_sandbox_declared is False
    config.python_sandbox = "venv"
    assert config.python_sandbox_declared is True


def test_the_startup_default_is_not_a_statement():
    """Or every machine with conda would be a machine that asked for conda."""
    assert UserConfig().python_sandbox_declared is False


# --------------------------------------------------------------------------- #
# The option this replaced                                                     #
# --------------------------------------------------------------------------- #


def test_use_docker_python_is_read_as_the_docker_sandbox(monkeypatch, caplog):
    """It never had a consumer, so honouring it here is what it always claimed."""
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    ctx = _Ctx(_config(use_docker_python_declared=True))

    assert ctx.preferred_python_sandbox() == "docker"
    assert "useDockerPython" in caplog.text
    assert "pythonSandbox" in caplog.text


def test_the_deprecation_is_said_once(monkeypatch, caplog):
    """A command over a tree of parts asks per part."""
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    ctx = _Ctx(_config(use_docker_python_declared=True))

    for _ in range(5):
        ctx.preferred_python_sandbox()
    assert caplog.text.count("useDockerPython") == 1


def test_an_explicit_sandbox_outranks_the_deprecated_option(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    config = _config(use_docker_python_declared=True)
    config.python_sandbox = "conda"
    assert _Ctx(config).preferred_python_sandbox() == "conda"
