#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where a sandbox gets to say what is actually launched.

A sandbox whose interpreter is not on this machine has to turn the command it
was handed into a different command -- ``docker exec`` of the same argv today,
something else later. The awkward part is that there is more than one place a
command is launched from: this module runs one with ``subprocess``, and
``PythonRuntime`` prepends an interpreter and runs its own. A sandbox that
intercepted a ``run`` method caught whichever of the two its caller happened to
use, and the other one quietly ran on the host -- which is how the ``docker``
sandbox came to build its virtual environment with the host's interpreter while
its container sat beside it doing nothing.

So both go through ``_spawn``, and these say so. Nothing here needs a container:
what is under test is that the seam is consulted and that what it returns is
what runs.
"""

import asyncio
import sys
import types

import pytest

from partcad import runtime


def _ctx(tmp_path):
    return types.SimpleNamespace(user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path)))


ELSEWHERE = [sys.executable, "-c", "print('somewhere else')"]


class _Wrapped(runtime.Runtime):
    """A runtime that launches something other than what it was asked for."""

    def __init__(self, tmp_path):
        super().__init__(_ctx(tmp_path), "wrapped")
        self.asked = []

    def _spawn(self, cmd, cwd=None, env=None):
        self.asked.append((list(cmd), cwd, env))
        return ELSEWHERE, None, None


# --------------------------------------------------------------------------- #
# The seam decides                                                             #
# --------------------------------------------------------------------------- #


def test_run_launches_what_the_sandbox_says(tmp_path):
    made = _Wrapped(tmp_path)
    exitcode, stdout, stderr = made.run(["/not/an/interpreter"])

    assert exitcode == 0, stderr
    assert "somewhere else" in stdout


def test_run_async_launches_what_the_sandbox_says(tmp_path):
    made = _Wrapped(tmp_path)
    exitcode, stdout, stderr = asyncio.run(made.run_async(["/not/an/interpreter"], ""))

    assert exitcode == 0, stderr
    assert "somewhere else" in stdout


def test_the_seam_is_told_the_directory_and_the_environment(tmp_path):
    """Both belong to the process being launched, so both are its sandbox's.

    'docker' moves the directory into a '-w' flag and drops the environment,
    because neither belongs to the client it would otherwise be applied to.
    A sandbox that is handed only the argv cannot make that call.
    """
    made = _Wrapped(tmp_path)
    made.run(["/x"], cwd=str(tmp_path), env={"A": "1"})

    assert made.asked[-1] == (["/x"], str(tmp_path), {"A": "1"})


def test_a_sandbox_that_says_nothing_launches_what_it_was_handed(tmp_path):
    """The default, and what every sandbox but 'docker' does."""
    made = runtime.Runtime(_ctx(tmp_path), "plain")
    exitcode, stdout, stderr = made.run([sys.executable, "-c", "print('here')"])

    assert exitcode == 0, stderr
    assert "here" in stdout


# --------------------------------------------------------------------------- #
# The other launch point                                                       #
# --------------------------------------------------------------------------- #


@pytest.fixture
def python_runtime(tmp_path):
    """A 'PythonRuntime' that runs this interpreter and provisions nothing.

    Enough of one to reach the launch inside 'run_onced', which is the half of
    the pair that does not go through 'Runtime.run'.
    """
    from partcad import runtime_python

    made = runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11")
    made.exec_path = sys.executable
    made.provisioned = True
    return made


def test_the_python_runtime_launch_goes_through_the_seam_too(python_runtime, monkeypatch):
    """The one that prepends an interpreter, and used to launch it directly."""
    asked = []

    def _spawn(cmd, cwd=None, env=None):
        asked.append(list(cmd))
        return ELSEWHERE, None, None

    monkeypatch.setattr(python_runtime, "_spawn", _spawn)
    exitcode, stdout, _ = python_runtime.run_onced(["-c", "print('not this one')"])

    assert exitcode == 0
    assert "somewhere else" in stdout
    # It is handed the whole command line, interpreter included, because that
    # is what a sandbox has to wrap.
    assert asked[-1][0] == sys.executable


def test_standard_input_reaches_the_interpreter(python_runtime):
    """It is written to a pipe as bytes, and read back as bytes.

    Asking Popen to encode as well made this path raise on every call that had
    anything to say -- and a strict decode of the output would have raised on
    the Windows code page that 'process_output' exists to survive.
    """
    exitcode, stdout, stderr = python_runtime.run_onced(
        ["-c", "import sys; print(sys.stdin.read().upper())"], stdin="a request"
    )

    assert exitcode == 0, stderr
    assert "A REQUEST" in stdout
