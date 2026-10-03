#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Saying why a package's own image was not what ran it.

A package names a `dockerImage` because something it needs cannot be installed
by pip -- a native solver, a mesher with no wheel for this platform. Running it
anywhere else is the likeliest reason it then fails, and the failure, written by
the implementation, cannot say so: it does not know where it was run. This used
to be decided silently, and an FEA in a dev container failed with "the solver is
not available -- run with a container runtime available" while one was running.
"""

import logging

import pytest

from partcad import context as pc_context
from partcad import runtime, runtime_python_docker
from partcad_utils.user_config import UserConfig

IMAGE = "ghcr.io/example/solver:1"


class _Ctx:
    """A context reduced to what explaining a skipped image reads."""

    def __init__(self, user_config):
        self.user_config = user_config
        self.docker_image_notes = {}
        self.docker_image_fallback_warned = set()

    _sandbox_was_declared = pc_context.Context._sandbox_was_declared
    _why_not_docker = pc_context.Context._why_not_docker
    _note_image_skipped = pc_context.Context._note_image_skipped
    docker_image_note = pc_context.Context.docker_image_note


@pytest.fixture(autouse=True)
def _a_machine_that_has_said_nothing(monkeypatch, tmp_path):
    """See the fixture of the same name in test_python_sandbox_default.py."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_PYTHON_SANDBOX", raising=False)
    runtime_python_docker._UNAVAILABLE_REASONS.clear()


def _skip(ctx, sandbox="conda", version="3.11"):
    ctx._note_image_skipped(IMAGE, ctx._why_not_docker(sandbox, version))
    return ctx.docker_image_note(IMAGE)


def test_a_stated_sandbox_is_named_as_the_reason(monkeypatch):
    config = UserConfig()
    config.python_sandbox = "conda"
    note = _skip(_Ctx(config))
    assert IMAGE in note
    assert "'pythonSandbox'" in note


def test_no_container_runtime_is_named_as_the_reason(monkeypatch):
    monkeypatch.setattr(runtime, "docker_enabled", lambda config: False)
    note = _skip(_Ctx(UserConfig()))
    assert "Docker is not available here" in note


def test_a_daemon_that_cannot_see_these_files_is_named_as_the_reason(monkeypatch):
    """The dev container: Docker answers, and the sandbox still cannot be used."""
    monkeypatch.setattr(runtime, "docker_enabled", lambda config: True)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda: object())
    monkeypatch.setattr(runtime_python_docker, "resolve_image", lambda client, image, version="": image)
    monkeypatch.setattr(runtime_python_docker, "mount_sources", lambda client, image: False)

    own = runtime_python_docker.image_for("3.11")
    assert not runtime_python_docker.image_available(own, "3.11")

    note = _skip(_Ctx(UserConfig()))
    assert "cannot see this machine's files" in note


def test_a_pull_that_failed_is_named_as_the_reason(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda: object())

    def refuse(client, image, version=""):
        raise runtime.SandboxUnavailable("denied")

    monkeypatch.setattr(runtime_python_docker, "resolve_image", refuse)
    assert not runtime_python_docker.image_available(IMAGE)
    assert "could not be pulled" in runtime_python_docker.unavailable_reason(IMAGE)


def test_an_image_that_became_available_has_no_reason_left(monkeypatch):
    runtime_python_docker._UNAVAILABLE_REASONS[IMAGE] = "stale"
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda: object())
    monkeypatch.setattr(runtime_python_docker, "resolve_image", lambda client, image, version="": image)
    monkeypatch.setattr(runtime_python_docker, "mount_sources", lambda client, image: None)
    assert runtime_python_docker.image_available(IMAGE)
    assert runtime_python_docker.unavailable_reason(IMAGE) is None


def test_it_is_a_warning_and_it_is_said_once(monkeypatch, caplog):
    config = UserConfig()
    config.python_sandbox = "conda"
    ctx = _Ctx(config)
    with caplog.at_level(logging.WARNING, logger="partcad"):
        _skip(ctx)
        _skip(ctx)
    said = [r for r in caplog.records if IMAGE in r.getMessage() and r.levelno == logging.WARNING]
    assert len(said) == 1


def test_an_image_nobody_asked_for_has_no_note():
    ctx = _Ctx(UserConfig())
    assert ctx.docker_image_note(None) is None
    assert ctx.docker_image_note(IMAGE) is None


def test_a_failure_carries_the_note():
    """What the user reads is the failure, not the warning several screens up."""
    import types

    from partcad.shape import sandbox_note

    ctx = _Ctx(UserConfig())
    ctx._note_image_skipped(IMAGE, "it ran in the 'conda' sandbox")
    impl = types.SimpleNamespace(container=None, docker_image=IMAGE)
    assert sandbox_note(ctx, impl) == "\n" + ctx.docker_image_note(IMAGE)
    # One that runs in a container of its own runs there or not at all.
    assert sandbox_note(ctx, types.SimpleNamespace(container={"image": "x"}, docker_image=IMAGE)) == ""
    assert sandbox_note(ctx, types.SimpleNamespace(container=None, docker_image=None)) == ""


def test_a_sandbox_the_caller_named_is_named_as_the_reason(monkeypatch):
    """Not "Docker is unavailable", which would send the reader after the wrong thing."""
    monkeypatch.setattr(runtime, "docker_enabled", lambda config: True)
    ctx = _Ctx(UserConfig())
    ctx._note_image_skipped(IMAGE, ctx._why_not_docker("conda", "3.11", requested=True))
    note = ctx.docker_image_note(IMAGE)
    assert "asked to run in" in note
    assert "not available" not in note


def test_mounts_that_miss_a_needed_directory_make_the_image_unavailable(monkeypatch, tmp_path):
    """Said before PartCAD chooses Docker, where it can still choose something else,
    rather than when the container starts and every part fails."""
    import tempfile

    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda: object())
    monkeypatch.setattr(runtime_python_docker, "resolve_image", lambda client, image, version="": image)
    covered = [(tempfile.gettempdir(), "/daemon/tmp"), (runtime_python_docker.INSTALL_DIR, "/daemon/install")]
    monkeypatch.setattr(runtime_python_docker, "mount_sources", lambda client, image: covered)

    assert runtime_python_docker.image_available(IMAGE)
    # A package somewhere none of this container's mounts reaches.
    package = "/opt/elsewhere/package"
    assert runtime_python_docker.misses(IMAGE, [package])
    assert package in runtime_python_docker.unavailable_reason(IMAGE)
    assert not runtime_python_docker.image_available(IMAGE, needed=[package])
