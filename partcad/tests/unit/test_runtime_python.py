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
import pytest
import sys

import partcad as pc
from partcad.user_config import UserConfig

@pytest.fixture
def config_for():
    def _config_for(runtime):
        user_config = UserConfig()
        user_config.set("python_sandbox", runtime)
        return user_config
    return _config_for

def test_runtime_python_version_3_9_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 9:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("partcad/tests", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.9")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 10:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("partcad/tests", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.10")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 11:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("partcad/tests", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.11")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_none(config_for):
    if sys.version_info[0] != 3 or sys.version_info[1] != 12:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    ctx = pc.Context("partcad/tests", user_config=config_for("none"))
    runtime = ctx.get_python_runtime("3.12")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.12")


def test_runtime_python_version_3_9_conda(config_for):
    ctx = pc.Context("partcad/tests", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.9")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_conda(config_for):
    ctx = pc.Context("partcad/tests", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.10")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_conda(config_for):
    ctx = pc.Context("partcad/tests", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.11")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_conda(config_for):
    ctx = pc.Context("partcad/tests", user_config=config_for("conda"))
    runtime = ctx.get_python_runtime("3.12")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.12")
