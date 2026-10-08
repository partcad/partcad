#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Importing a KiCad PCB on a machine with no container runtime.

`kicad-cli` is run in a container by default, and the factory used to go
straight to `docker.from_env()`. On a machine with nothing behind the socket
that raised the SDK's own "Error while fetching server API version:
('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))" --
out of `pc render`, `pc export` and `pc ide view` alike, naming neither the PCB
nor anything the reader could do next.

Nothing here starts a container.
"""

import asyncio
import types

import pytest

from partcad import part_factory_kicad, runtime


def _ctx(tmp_path, use_docker_kicad):
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(
            internal_state_dir=str(tmp_path),
            # Already folded in by `UserConfig`: 'useDockerKicad' is only true
            # when 'useDocker' is. So the factory has one question left to ask.
            use_docker_kicad=use_docker_kicad,
        )
    )


def test_no_container_runtime_is_reported_as_such(tmp_path, monkeypatch):
    """`SandboxUnavailable`, and not whatever the Docker SDK happens to raise.

    The type is what makes it an answer rather than a fault everywhere it is
    handled: `pc test` skips on it, and the daemon reports it to the IDE
    without a traceback.
    """
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    with pytest.raises(runtime.SandboxUnavailable) as raised:
        asyncio.run(part_factory_kicad.get_runtime(_ctx(tmp_path, True)))

    message = str(raised.value)
    # What wanted a container...
    assert "kicad-cli" in message
    # ...and both ways out of it.
    assert "Start Docker" in message
    assert "useDockerKicad" in message


def test_the_native_path_does_not_ask_for_a_container(tmp_path, monkeypatch):
    """A machine told to use its own KiCad never touches the daemon."""

    def _must_not_be_asked():
        raise AssertionError("the daemon was asked although 'useDockerKicad' is false")

    monkeypatch.setattr(runtime, "docker_available", _must_not_be_asked)
    _, uses_docker = asyncio.run(part_factory_kicad.get_runtime(_ctx(tmp_path, False)))
    assert uses_docker is False


def _counting_acquire(monkeypatch):
    """Stand in for the container, recording which thread asked for it."""
    import threading

    from partcad import container_mounts

    asked = []

    class Endpoint:
        name = "partcad-kicad-test"

    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(container_mounts, "spec_for", lambda *args, **kwargs: object())
    monkeypatch.setattr(container_mounts, "acquire", lambda spec: asked.append(threading.get_ident()) or Endpoint())
    monkeypatch.setattr(runtime.Runtime, "use_container", lambda self, endpoint: None)
    return asked


def test_the_container_is_asked_for_once_per_context(tmp_path, monkeypatch):
    """Every board after the first reuses it: asking again is the Docker round trips again."""
    asked = _counting_acquire(monkeypatch)
    ctx = _ctx(tmp_path, True)

    async def two_boards():
        return await part_factory_kicad.get_runtime(ctx), await part_factory_kicad.get_runtime(ctx)

    first, second = asyncio.run(two_boards())

    assert len(asked) == 1
    assert first is second


def test_the_container_is_asked_for_off_the_event_loop(tmp_path, monkeypatch):
    """Starting one is seconds of blocking calls; every other part waits on the loop meanwhile."""
    import threading

    asked = _counting_acquire(monkeypatch)

    async def on_the_loop():
        await part_factory_kicad.get_runtime(_ctx(tmp_path, True))
        return threading.get_ident()

    loop_thread = asyncio.run(on_the_loop())

    assert asked and asked[0] != loop_thread
