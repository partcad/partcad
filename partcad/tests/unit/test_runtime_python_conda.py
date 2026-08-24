#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a conda sandbox actually asks conda for.

A sandbox is made by two conda commands, and whether it comes out usable is a
property of the two together - which is exactly what nothing here used to see. A
prefix created with the interpreter's ABI pinned and then populated by an
unconstrained second command had its interpreter swapped for the free-threaded
build of the same version, which no CAD wheel is built for.

Nothing is run: the commands are recorded and read. What went wrong was in the
arguments, and reproducing it for real means a conda solve per case.
"""

import os
import pathlib

import pytest

from partcad import runtime_python_conda
from partcad.runtime_python_conda import CondaPythonRuntime


class _FakeProcess:
    """A process that ran nothing, said nothing and succeeded."""

    returncode = 0

    def communicate(self):
        return "{}", ""


@pytest.fixture
def recorded_commands(monkeypatch):
    """Every command 'subprocess.Popen' is handed, in order."""
    commands = []

    def popen(args, **kwargs):
        commands.append(list(args))
        return _FakeProcess()

    monkeypatch.setattr(runtime_python_conda.subprocess, "Popen", popen)
    return commands


def _bare_runtime(path, version, is_mamba=True):
    """A CondaPythonRuntime with just what once_conda_locked_attempt() reads.

    __init__ wants a full context, a lock file and a conda on PATH, none of which
    have anything to say about the command that gets built.
    """
    runtime = CondaPythonRuntime.__new__(CondaPythonRuntime)
    runtime.conda_path = "mamba" if is_mamba else "conda"
    runtime.is_mamba = is_mamba
    runtime.version = version
    runtime.path = str(path / ("pc-py-conda-" + version))
    runtime.variant_packages = []
    runtime.conda_initialized = False
    runtime.constraints_path = None
    runtime.initialized = True
    return runtime


@pytest.mark.parametrize("version", ["3.13", "3.14"])
def test_every_conda_command_pins_the_gil_abi(tmp_path, recorded_commands, version):
    """Both commands, not just the "create".

    The second one installs pip and pycairo and names no interpreter, so the
    solver was free to replace the one the first had just pinned - and it did,
    with the free-threaded build, because the two are the same version with the
    same build number and nothing else was there to break the tie.
    """
    _bare_runtime(tmp_path, version).once_conda_locked_attempt()

    assert len(recorded_commands) == 2, recorded_commands
    pin = "python_abi==%s=*_cp%s" % (version, version.replace(".", ""))
    for command in recorded_commands:
        assert pin in command, command


def test_nothing_is_pinned_below_the_free_threaded_builds(tmp_path, recorded_commands):
    """There are no two builds to tell apart before 3.13, and no pin that would.

    conda-forge's build strings there end in "_cpython" rather than "_cp312", so
    a "*_cp312" pin matches no package at all and fails the solve outright.
    """
    _bare_runtime(tmp_path, "3.12").once_conda_locked_attempt()

    assert not [spec for command in recorded_commands for spec in command if spec.startswith("python_abi")]


@pytest.mark.parametrize("is_mamba", [True, False])
def test_the_python_spec_is_the_fuzzy_one(tmp_path, recorded_commands, is_mamba):
    """"python==3.14" does not mean what it looks like it means.

    libmamba reads it as the 3.14 release exactly, which is 3.14.0 - the oldest
    patch of the line rather than the newest - and then the next solve wants to
    upgrade what it pinned. "=3.14" is the "3.14.*" both conda and mamba mean.
    """
    _bare_runtime(tmp_path, "3.14", is_mamba=is_mamba).once_conda_locked_attempt()

    create = recorded_commands[0]
    assert "python=3.14" in create, create
    assert "python==3.14" not in create, create


def test_discarding_the_prefix_forgets_what_described_it(tmp_path):
    """A rebuild has to leave nothing of the prefix behind, in memory either.

    Both of these were read off a prefix that no longer exists. A stale
    'constraints_path' fails every later install with "Could not open constraint
    file", and a stale 'initialized' has once() skip installing the CAD stack
    into the sandbox that was just rebuilt to receive it.
    """
    runtime = _bare_runtime(tmp_path, "3.14")
    os.makedirs(runtime.path)
    runtime.constraints_path = os.path.join(runtime.path, "partcad-constraints.txt")
    pathlib.Path(runtime.constraints_path).touch()

    runtime.discard_prefix()

    assert not os.path.exists(runtime.path)
    assert runtime.constraints_path is None
    assert runtime.initialized is False


def test_a_free_threaded_prefix_is_the_only_one_thrown_away(tmp_path):
    """Every other verify failure leaves the prefix for the next attempt.

    A prefix that failed to answer, or answered with the wrong version, may
    still be one an install can repair. A free-threaded one cannot be: no CAD
    wheel is built for that ABI, so there is nothing to install into it.
    """
    runtime = _bare_runtime(tmp_path, "3.14")
    os.makedirs(runtime.path)

    runtime.conda_free_threaded = False
    runtime.discard_if_free_threaded()
    assert os.path.exists(runtime.path)

    runtime.conda_free_threaded = True
    runtime.discard_if_free_threaded()
    assert not os.path.exists(runtime.path)
    assert runtime.conda_free_threaded is False
