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
    _sandbox_was_declared = pc_context.Context._sandbox_was_declared
    _image_available = pc_context.Context._image_available
    _docker_or_next_best = pc_context.Context._docker_or_next_best

    docker_images_available = None
    docker_sandbox_fallback_warned = False

    def __init_images__(self):
        self.docker_images_available = {}
        return self


@pytest.fixture(autouse=True)
def _a_machine_that_has_said_nothing(monkeypatch, tmp_path):
    """Whatever this machine says.

    'UserConfig' resolves a real '~/.partcad/config.yaml' and the real 'PC_*'
    environment, and every test here is about what happens when nobody has
    declared a sandbox -- so a contributor who has declared one would see these
    fail for a reason that is not in the code under test.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_PYTHON_SANDBOX", raising=False)


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


# --------------------------------------------------------------------------- #
# A container runtime is not a registry                                        #
# --------------------------------------------------------------------------- #
#
# A daemon answering says a container could be started. It says nothing about
# whether the image to start it from can be had, and on a machine that is
# offline, firewalled, or simply not allowed to pull, those are different
# answers -- so choosing docker there would fail every part against a registry
# the user never asked to talk to.


def _chooser(monkeypatch, available, **overrides):
    """A context that can or cannot get images, with docker running."""
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    from partcad import runtime_python_docker

    monkeypatch.setattr(runtime_python_docker, "image_available", lambda image, version="": available)
    return _Ctx(_config(**overrides)).__init_images__()


def test_an_image_that_cannot_be_had_is_not_a_sandbox(monkeypatch):
    made = _chooser(monkeypatch, available=False)
    assert made.preferred_python_sandbox() == "docker"
    assert made._docker_or_next_best("3.11") == made.user_config.python_sandbox


def test_an_image_that_can_be_had_is(monkeypatch):
    assert _chooser(monkeypatch, available=True)._docker_or_next_best("3.11") == "docker"


def test_the_registry_is_asked_once(monkeypatch):
    """A command over a tree of parts must not ask per part."""
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    from partcad import runtime_python_docker

    asked = []
    monkeypatch.setattr(runtime_python_docker, "image_available", lambda image, version="": asked.append(image) or True)
    made = _Ctx(_config()).__init_images__()
    for _ in range(5):
        made._docker_or_next_best("3.11")
    assert len(asked) == 1


def test_a_stated_preference_is_not_second_guessed(monkeypatch):
    """Being unable to do what was asked is a failure, not a reason to do
    something else. The fallback is only ever for a choice PartCAD made."""
    made = _chooser(monkeypatch, available=False)
    # Assigning is what makes it stated -- that is how '--python-sandbox'
    # arrives, after the configuration has been read.
    made.user_config.python_sandbox = "docker"

    assert made._sandbox_was_declared() is True
    assert made.preferred_python_sandbox() == "docker"
