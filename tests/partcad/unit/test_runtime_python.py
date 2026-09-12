#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import importlib.util
import os
import shutil
import sys
import venv

import pytest

import partcad as pc
from partcad.user_config import UserConfig


def _conda_is_installed():
    return shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None


@pytest.fixture
def ambient_python(tmp_path, monkeypatch):
    """An empty interpreter for the 'none' sandbox to be, and to install into.

    'none' is not a sandbox that has an environment; it is the environment you
    are already in, resolved as 'which python' (see NonePythonRuntime). So a
    test that asks one to run anything provisions PartCAD's whole CAD stack into
    whatever interpreter is running pytest -- which in a checkout is '.venv', and
    that is where 'cadquery' and the VTK-carrying 'cadquery-ocp' used to arrive
    on top of the 'cadquery-ocp-novtk' that 'poetry install' put there.

    Making one here and putting it first on PATH moves both halves of that into
    'tmp_path': the interpreter the sandbox installs into and runs, and -- via
    'internal_state_dir' -- the directory its install guards live in. Nothing is
    shared with the environment running the tests, so the suite stays in
    PartCAD's own environment and this test stops rewriting it.

    Both halves, or neither is enough. Leaving the state directory shared would
    leave guard files behind claiming the stack is installed in "the none
    sandbox" after the interpreter that had it has been deleted -- and the next
    person to run PartCAD with 'pythonSandbox: none' would get the install
    skipped and a wrapper failing on an import of something nobody installed.

    With pip, because the sandbox installs with it. "Empty" here means no CAD
    stack, which is the thing that was leaking.
    """
    target = tmp_path / "ambient"
    venv.EnvBuilder(with_pip=True).create(str(target))
    binaries = target / ("Scripts" if os.name == "nt" else "bin")
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ.get("PATH", ""))

    user_config = UserConfig()
    user_config.python_sandbox = "none"
    user_config.internal_state_dir = str(tmp_path / "state")
    return user_config


@pytest.fixture
def config_for():
    """A user configuration that really selects the named sandbox.

    Assigned to the attribute rather than passed to 'set()'. 'UserConfig' reads
    every option into an attribute of its own in '__init__' -- 'python_sandbox'
    from 'pythonSandbox' -- and 'set()' is vyper's, which writes the underlying
    config key. So 'set("python_sandbox", ...)' wrote a key nothing reads and
    left the attribute at the host's default: every test below ran on whatever
    sandbox the host happened to choose, and the conda ones passed on a host
    with no conda by testing something else entirely.
    """

    def _config_for(runtime):
        if runtime == "conda" and not _conda_is_installed():
            pytest.skip("conda is not installed on this host")
        user_config = UserConfig()
        user_config.python_sandbox = runtime
        return user_config

    return _config_for


@pytest.mark.slow
def test_runtime_python_version_3_9_none(ambient_python):
    if sys.version_info[0] != 3 or sys.version_info[1] != 9:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=ambient_python)
    runtime = ctx.get_python_runtime("3.9")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.9")


@pytest.mark.slow
def test_runtime_python_version_3_10_none(ambient_python):
    if sys.version_info[0] != 3 or sys.version_info[1] != 10:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=ambient_python)
    runtime = ctx.get_python_runtime("3.10")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.10")


@pytest.mark.slow
def test_runtime_python_version_3_11_none(ambient_python):
    if sys.version_info[0] != 3 or sys.version_info[1] != 11:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=ambient_python)
    runtime = ctx.get_python_runtime("3.11")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.11")


@pytest.mark.slow
def test_runtime_python_version_3_12_none(ambient_python):
    if sys.version_info[0] != 3 or sys.version_info[1] != 12:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=ambient_python)
    runtime = ctx.get_python_runtime("3.12")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.12")


def test_runtime_python_version_3_9_conda(config_for):
    ctx = pc.Context("tests/partcad", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.9")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_conda(config_for):
    ctx = pc.Context("tests/partcad", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.10")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_conda(config_for):
    ctx = pc.Context("tests/partcad", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.11")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_conda(config_for):
    ctx = pc.Context("tests/partcad", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.12")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.12")
