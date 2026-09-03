#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'venv' sandbox, and where an ambient-interpreter sandbox installs to.

Two things are covered here and they are two halves of one problem: a sandbox
has to install packages with the same interpreter it later runs them with. The
'none' sandbox did not -- it ran the host's Python and installed with an
interpreter path inside its own directory, which is not an environment and holds
no interpreter at all -- and 'venv' exists so that the fallback is a real
environment rather than the user's own Python.

Nothing here provisions a CAD stack. Building an environment and filling it with
build123d takes minutes and is what the gated end-to-end test at the bottom is
for; the rest asks the runtime objects what they would do.
"""

import asyncio
import os
import sys

import pytest

import partcad as pc
from partcad import runtime_python_all
from partcad.runtime_python_none import NonePythonRuntime
from partcad.runtime_python_venv import VenvPythonRuntime
from partcad.user_config import UserConfig

VERSION = "%d.%d" % (sys.version_info[0], sys.version_info[1])


@pytest.fixture
def config_for():
    def _config_for(runtime):
        user_config = UserConfig()
        # The attribute, not 'set()': see the same fixture in
        # 'test_runtime_python.py' for why that one selects nothing.
        user_config.python_sandbox = runtime
        return user_config

    return _config_for


@pytest.fixture
def ctx(config_for):
    return pc.Context("tests/partcad", user_config=config_for("venv"))


# --------------------------------------------------------------------------- #
# 'none': install where you run                                               #
# --------------------------------------------------------------------------- #


def test_the_none_sandbox_installs_with_the_interpreter_it_runs(config_for):
    """Its directory is not an environment, so nothing lives in '<it>/bin'.

    'ensure_*' fills the install path in with the runtime's own directory, and
    resolving that to '<sandbox>/bin/python' named a file that never existed --
    so on a clean machine the install could not start, and on a dirty one it
    installed somewhere the wrapper would not look.
    """
    context = pc.Context("tests/partcad", user_config=config_for("none"))
    runtime = context.get_python_runtime(VERSION)
    assert isinstance(runtime, NonePythonRuntime)
    assert runtime.exec_path is not None

    # What a run uses, and what an install uses, are the same interpreter.
    assert runtime.get_venv_python_path() == runtime.exec_path
    assert runtime.get_venv_python_path(path=runtime.path) == runtime.exec_path
    assert not runtime.get_venv_python_path(path=runtime.path).startswith(runtime.path)


def test_a_conda_prefix_still_resolves_inside_itself(config_for):
    """The rule is about *this* runtime's directory, not about any path given.

    A conda prefix and a v-env both really do hold their interpreter, and the
    fix above must not redirect those to the host's.
    """
    context = pc.Context("tests/partcad", user_config=config_for("none"))
    runtime = context.get_python_runtime(VERSION)
    elsewhere = os.path.join(os.path.dirname(runtime.path), "some-conda-prefix")
    assert runtime.get_venv_python_path(path=elsewhere).startswith(elsewhere)


# --------------------------------------------------------------------------- #
# 'venv': a real environment of PartCAD's own                                 #
# --------------------------------------------------------------------------- #


def test_the_venv_sandbox_is_selectable(ctx):
    runtime = ctx.get_python_runtime(VERSION)
    assert isinstance(runtime, VenvPythonRuntime)
    assert runtime.sandbox == "venv"
    # Named after the sandbox and the version, like every other one, so two
    # versions are two environments.
    assert runtime.path.endswith("pc-py-venv-" + VERSION)


def test_the_factory_knows_the_name():
    assert runtime_python_all.create.__module__ == "partcad.runtime_python_all"
    with pytest.raises(Exception, match="invalid python runtime"):
        runtime_python_all.create(None, VERSION, "not-a-sandbox")


def test_the_venv_interpreter_is_inside_the_sandbox(ctx):
    """Which is the whole point: it installs and runs in its own directory."""
    runtime = ctx.get_python_runtime(VERSION)
    assert os.path.dirname(os.path.dirname(runtime.venv_exec_path)) == runtime.path
    assert os.path.basename(runtime.venv_exec_path) == runtime.exec_name


def test_the_host_interpreter_is_a_real_file(ctx):
    """The environment is built *from* it, so it has to exist before anything."""
    runtime = ctx.get_python_runtime(VERSION)
    assert os.path.exists(runtime.host_exec_path)


def test_an_unbuilt_sandbox_runs_the_host_interpreter(ctx, tmp_path):
    """Until the environment exists, the host's is what creates it.

    'exec_path' is what the command machinery reads, so it has to be the host's
    for the length of the '-m venv' that builds the environment and the
    environment's own for everything after it.
    """
    runtime = ctx.get_python_runtime(VERSION)
    runtime.path = str(tmp_path / ("pc-py-venv-" + VERSION))
    runtime.exec_path = runtime.host_exec_path

    command = runtime._create_locked()
    assert command == ["-m", "venv", "--upgrade-deps", runtime.path]
    assert runtime.exec_path == runtime.host_exec_path


def test_an_existing_environment_is_not_rebuilt(ctx, tmp_path):
    """A sandbox is built once; every render afterwards just uses it."""
    runtime = ctx.get_python_runtime(VERSION)
    runtime.path = str(tmp_path / ("pc-py-venv-" + VERSION))
    os.makedirs(os.path.dirname(runtime.venv_exec_path), exist_ok=True)
    with open(runtime.venv_exec_path, "w") as f:
        f.write("")

    assert runtime._create_locked() == []
    assert runtime.exec_path == runtime.venv_exec_path


# --------------------------------------------------------------------------- #
# What the fallback is                                                        #
# --------------------------------------------------------------------------- #


def test_venv_is_the_fallback_when_conda_is_absent(monkeypatch):
    """'none' was, and it is not a sandbox: it installs into the user's Python."""
    import partcad_utils.user_config as user_config_module

    monkeypatch.setattr(user_config_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(user_config_module.importlib.util, "find_spec", lambda name: None)
    assert UserConfig().python_sandbox == "venv"


def test_conda_is_still_preferred_when_it_is_there(monkeypatch):
    """It is the only sandbox that can provision an interpreter version."""
    import partcad_utils.user_config as user_config_module

    monkeypatch.setattr(user_config_module.shutil, "which", lambda name: "/usr/bin/" + name)
    assert UserConfig().python_sandbox == "conda"


# --------------------------------------------------------------------------- #
# End to end, which really builds an environment                              #
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_the_venv_sandbox_runs_the_interpreter_it_built(ctx):
    """And it is the one inside the sandbox, not the host's."""
    runtime = ctx.get_python_runtime(VERSION)
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0, errors
    assert version_string.startswith("Python " + VERSION)
    assert os.path.exists(runtime.venv_exec_path)
    assert runtime.exec_path == runtime.venv_exec_path
