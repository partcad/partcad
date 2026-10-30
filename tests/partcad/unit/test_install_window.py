#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A sandbox install says how long it may take, so that a client waits for pip's own answer.

pip says nothing while it downloads, and a client gives up on a daemon that says
nothing for five minutes. A cold sandbox's first install on a slow network
outlasted that, and the command ended in "the PartCAD service stopped
responding" while the daemon was still installing -- before pip could say what
was actually wrong (see 'runtime_python.INSTALL_WINDOW_SECONDS').

What is pinned here is the daemon's half: every install, and every sandbox and
layer it creates, runs inside a window that names it, announced through the same
log hook the daemon forwards to its client. The client's half -- waiting that long, and
naming the install if even that runs out -- is in 'tests/partcad_client'.
"""

import asyncio
import os
import sys
import types

import pytest

from partcad import runtime_python, runtime_python_venv
from partcad_utils import logging_remote_server, timeouts


def _ctx(tmp_path):
    return types.SimpleNamespace(user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path)))


@pytest.fixture
def python_runtime(tmp_path):
    """A 'PythonRuntime' that runs this interpreter and provisions nothing."""
    made = runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11")
    made.exec_path = sys.executable
    made.provisioned = True
    os.makedirs(made.path, exist_ok=True)
    return made


@pytest.fixture
def announced():
    """Everything the daemon's log hook would send a client, in order."""
    events = []
    logging_remote_server.init(events.append)
    try:
        yield events
    finally:
        logging_remote_server.fini()


def _windows(events):
    return [(e["kind"], e[timeouts.SECONDS], e.get(timeouts.REASON)) for e in events if e["kind"] in timeouts.KINDS]


def _runs(runtime, monkeypatch, answer):
    """Stand ``answer(cmd)`` in for every command the runtime runs, both flavours."""

    def run(cmd, stdin="", cwd=None, session=None, path=None):
        return answer(cmd)

    async def run_async(cmd, stdin="", cwd=None, session=None, path=None):
        return answer(cmd)

    monkeypatch.setattr(runtime, "run_onced_locked", run)
    monkeypatch.setattr(runtime, "run_async_onced_locked", run_async)


def test_the_window_is_longer_than_a_client_waits_by_default():
    """Otherwise it would change nothing: a window only ever lengthens the wait."""
    from partcad_client.client import DEFAULT_IDLE_TIMEOUT

    assert runtime_python.INSTALL_WINDOW_SECONDS > DEFAULT_IDLE_TIMEOUT


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_pip_runs_inside_a_window_that_names_the_install(python_runtime, announced, monkeypatch, asynchronous):
    path = python_runtime.path
    while_pip_ran = []

    def pip(cmd):
        while_pip_ran.extend(_windows(announced))
        return 0, "", ""

    _runs(python_runtime, monkeypatch, pip)

    if asynchronous:
        asyncio.run(python_runtime.install_async_onced_locked("cq_warehouse", path))
    else:
        python_runtime.install_onced_locked("cq_warehouse", path)

    window = runtime_python.INSTALL_WINDOW_SECONDS
    reason = "installing cq_warehouse in " + path
    assert while_pip_ran == [("timeout_start", window, reason)]
    assert _windows(announced) == [("timeout_start", window, reason), ("timeout_end", window, reason)]


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_the_window_closes_when_the_install_fails(python_runtime, announced, monkeypatch, asynchronous):
    """A window left open would stretch every wait after it on that request."""

    def pip(cmd):
        raise OSError("no interpreter")

    _runs(python_runtime, monkeypatch, pip)

    with pytest.raises(OSError):
        if asynchronous:
            asyncio.run(python_runtime.install_async_onced_locked("cq_warehouse", python_runtime.path))
        else:
            python_runtime.install_onced_locked("cq_warehouse", python_runtime.path)

    assert [kind for kind, _, _ in _windows(announced)] == ["timeout_start", "timeout_end"]


def test_an_install_already_recorded_opens_no_window(python_runtime, announced, monkeypatch):
    """The guard makes it a stat(); there is nothing to wait for."""
    _runs(python_runtime, monkeypatch, lambda cmd: (0, "", ""))
    python_runtime.install_onced_locked("cq_warehouse", python_runtime.path)
    announced.clear()

    python_runtime.install_onced_locked("cq_warehouse", python_runtime.path)

    assert _windows(announced) == []


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_creating_the_sandbox_runs_inside_a_window_that_names_it(tmp_path, announced, monkeypatch, asynchronous):
    """The first silence of all: the base environment, before anything is installed into it.

    'venv --upgrade-deps' downloads pip. Run against an index that answers
    slowly, it is where a fresh '$HOME' first went quiet for longer than the
    client waits -- before any 'pip install' had started.
    """
    sandbox = runtime_python_venv.VenvPythonRuntime(_ctx(tmp_path), "3.11")
    while_created = []

    def run(cmd):
        if cmd[:2] == ["-m", "venv"]:
            while_created.extend(_windows(announced))
        return 0, "", ""

    async def nothing_installed(self):
        pass

    _runs(sandbox, monkeypatch, run)
    monkeypatch.setattr(sandbox, "_created", lambda exitcode, stderr: None)
    # What the base installs afterwards is the tests above; this is the creation alone.
    monkeypatch.setattr(runtime_python.PythonRuntime, "once", lambda self: None)
    monkeypatch.setattr(runtime_python.PythonRuntime, "once_async", nothing_installed)

    if asynchronous:
        asyncio.run(sandbox.once_async())
    else:
        sandbox.once()

    window = runtime_python.INSTALL_WINDOW_SECONDS
    reason = "creating the sandbox " + sandbox.path
    assert while_created == [("timeout_start", window, reason)]
    assert _windows(announced) == [("timeout_start", window, reason), ("timeout_end", window, reason)]


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_creating_a_layer_runs_inside_a_window_that_names_it(
    python_runtime, announced, monkeypatch, tmp_path, asynchronous
):
    """'venv --upgrade-deps' downloads pip, which is the same silence."""
    layer = str(tmp_path / (runtime_python.VENV_PREFIX + "0123456789abcdef"))
    session = {"name": "0123456789abcdef", "path": layer, "missing": [], "dirty": True}
    while_venv_ran = []

    def run(cmd):
        if cmd[:2] == ["-m", "venv"]:
            while_venv_ran.extend(_windows(announced))
            os.makedirs(layer)
        if tuple(cmd) == runtime_python.BASE_SITE_DIRS_COMMAND:
            return 0, "/base/site-packages\n", ""
        return 0, "", ""

    _runs(python_runtime, monkeypatch, run)

    if asynchronous:
        asyncio.run(python_runtime.provision_layer_async_onced_locked(session))
    else:
        python_runtime.provision_layer_onced_locked(session)

    window = runtime_python.INSTALL_WINDOW_SECONDS
    reason = "creating the layer " + layer
    assert while_venv_ran == [("timeout_start", window, reason)]
    assert _windows(announced) == [("timeout_start", window, reason), ("timeout_end", window, reason)]
