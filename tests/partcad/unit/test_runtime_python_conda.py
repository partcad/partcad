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

from partcad import logging as pc_logging
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
    runtime.conda_free_threaded = False
    runtime.conda_last_error = None
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
    """ "python==3.14" does not mean what it looks like it means.

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


class _ScriptedProcess:
    """A process that says what the script told it to say."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self):
        return self._stdout, self._stderr


@pytest.fixture
def scripted_commands(monkeypatch):
    """Drive 'subprocess.Popen' from a queue of (returncode, stdout, stderr).

    Returns (commands, script): append outcomes to 'script' before the call and
    read the commands that were run out of 'commands' afterwards. A call past the
    end of the script succeeds silently, which is what a healthy conda does.
    """
    commands = []
    script = []

    def popen(args, **kwargs):
        commands.append(list(args))
        if script:
            return _ScriptedProcess(*script.pop(0))
        return _FakeProcess()

    monkeypatch.setattr(runtime_python_conda.subprocess, "Popen", popen)
    return commands, script


# glibc's, not conda's: check_pf.c calls __libc_fatal() and kills the process
# when the netlink socket getaddrinfo() enumerates interfaces over answers with
# an unexpected errno. 9 is EBADF. Seen on ubuntu-24.04 in Standalone job
# 98777554923, and gone on the retry.
_NETLINK = "Unexpected error 9 on netlink descriptor 9.\n"


def test_a_recovered_conda_create_does_not_fail_the_run(tmp_path, scripted_commands):
    """A provisioning error the code retries past must not fail the command.

    This is the whole bug. `pc render` in Standalone job 98777554923 hit this,
    retried, built the sandbox, ran every wrapper out of it and rendered
    everything -- and then exited 1 with a bare `Aborted.`, because
    `pc_logging.error()` had set the process-wide `had_errors` flag on the way
    through and `process_result()` reads it after the work is done. A CLI that
    renders everything successfully and then aborts is telling the user nothing
    they can act on.
    """
    commands, script = scripted_commands
    script.append((0, "", _NETLINK))
    runtime = _bare_runtime(tmp_path, "3.13")

    runtime.once_conda_locked_attempt()

    assert runtime.conda_initialized is True
    assert pc_logging.had_errors is False, "a recovered provisioning error still fails the command"
    # Two creates: the one glibc killed, and the retry that worked.
    creates = [command for command in commands if "create" in command]
    assert len(creates) == 2, commands


def test_a_sporadic_create_failure_is_retried_before_pip_is_asked_to_populate_it(tmp_path, scripted_commands):
    """The retry has to happen before the second command, not after it.

    Falling through to "conda install pip" against a prefix that was never
    created is what produced the "Not a conda environment" line in that job: a
    second, louder, wholly derivative failure that named the sandbox rather than
    the thing that broke it.
    """
    commands, script = scripted_commands
    script.append((0, "", _NETLINK))
    runtime = _bare_runtime(tmp_path, "3.13")

    runtime.once_conda_locked_attempt()

    assert [command[1] for command in commands] == ["create", "create", "install"], commands


def test_an_unrecognised_create_failure_is_still_only_a_warning(tmp_path, scripted_commands):
    """Severity is not the attempt's call to make.

    `once_conda_holding_install_lock()` retries the attempt and then raises. An
    attempt that reports at error severity has already decided the command
    fails, whatever the caller goes on to do about it.
    """
    commands, script = scripted_commands
    script.append((0, "", "something nobody has seen before\n"))
    runtime = _bare_runtime(tmp_path, "3.13")

    runtime.once_conda_locked_attempt()

    assert pc_logging.had_errors is False
    assert [command[1] for command in commands] == ["create", "install"], commands


def test_a_failed_pip_install_is_a_warning_and_leaves_the_sandbox_uninitialized(tmp_path, scripted_commands):
    """The failure is reported by the return value, not by the log severity."""
    commands, script = scripted_commands
    script.append((0, "{}", ""))
    script.append((1, "", "could not install pip\n"))
    runtime = _bare_runtime(tmp_path, "3.13")

    runtime.once_conda_locked_attempt()

    assert runtime.conda_initialized is False
    assert pc_logging.had_errors is False


def test_provisioning_that_never_succeeds_is_fatal_and_names_the_cause(tmp_path, scripted_commands):
    """The one place that gets to fail the run, and it has to say what failed.

    "ERROR: Conda environment initialization failed" named nothing: not the
    sandbox, not the interpreter, not the diagnostic. Now that every attempt
    warns, this message is the only account of the failure there is.
    """
    commands, script = scripted_commands
    for _ in range(8):
        script.append((1, "", "could not install pip\n"))
    runtime = _bare_runtime(tmp_path, "3.13")

    with pytest.raises(Exception) as raised:
        runtime.once_conda_holding_install_lock()

    message = str(raised.value)
    assert "3.13" in message, message
    assert runtime.path in message, message
    assert "could not install pip" in message, message
