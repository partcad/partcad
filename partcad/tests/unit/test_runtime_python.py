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
from partcad.user_config import user_config


def test_runtime_python_version_3_9_none():
    if sys.version_info[0] != 3 or sys.version_info[1] != 9:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    user_config.sandbox_runtime = "none"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.9")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_none():
    if sys.version_info[0] != 3 or sys.version_info[1] != 10:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    user_config.sandbox_runtime = "none"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.10")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_none():
    if sys.version_info[0] != 3 or sys.version_info[1] != 11:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    user_config.sandbox_runtime = "none"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.11")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_none():
    if sys.version_info[0] != 3 or sys.version_info[1] != 12:
        pytest.skip("Make no assumptions about availability of other Python versions, other than the current one")
    user_config.sandbox_runtime = "none"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.12")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.12")


def test_runtime_python_version_3_9_conda():
    user_config.sandbox_runtime = "conda"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.9")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.9")


def test_runtime_python_version_3_10_conda():
    user_config.sandbox_runtime = "conda"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.10")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.10")


def test_runtime_python_version_3_11_conda():
    user_config.sandbox_runtime = "conda"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.11")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.11")


def test_runtime_python_version_3_12_conda():
    user_config.sandbox_runtime = "conda"
    ctx = pc.Context("partcad/tests")
    runtime = ctx.get_python_runtime("3.12")
    version_string, errors = asyncio.run(runtime.run_async(["--version"]))
    assert errors == ""
    assert version_string.startswith("Python 3.12")
