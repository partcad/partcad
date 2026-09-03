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
import shutil

import pytest
import sys

import partcad as pc
from partcad.user_config import UserConfig


def _conda_is_installed():
    return shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None


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


def test_runtime_python_version_3_9_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 9:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.9")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 10:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.10")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 11:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.11")
    exitcode, version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert exitcode == 0
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 12:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("tests/partcad", user_config=config_for("none"))
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
