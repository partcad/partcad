#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PYTHON* sweep that replaced the sandbox interpreters' '-I' flag."""

import os
import subprocess
import sys
import types

import pytest

import partcad as pc
from partcad import python_env
from partcad.runtime_python import PythonRuntime


@pytest.fixture
def sandbox_python_flags(tmp_path):
    """The flags a real PythonRuntime hands to a sandbox interpreter.

    Built through __init__, since the flags are what __init__ decides; the
    context only has to answer where the sandbox would live.
    """

    class _Ctx:
        user_config = types.SimpleNamespace(internal_state_dir=str(tmp_path))

    return PythonRuntime(_Ctx(), "none").python_flags


def test_sanitize_drops_every_python_variable():
    env = {
        "PYTHONPATH": "/somebody/elses/packages",
        "PYTHONHOME": "/somebody/elses/prefix",
        "PYTHONSTARTUP": "/somebody/elses/startup.py",
        "PYTHONWARNINGS": "error",
        "PATH": "/usr/bin",
    }

    python_env.sanitize(env)

    assert [name for name in env if name.startswith("PYTHON")] == list(python_env.PARTCAD_PYTHON_ENV)
    # Only the PYTHON* namespace is swept: the rest of the environment is what
    # the sandbox needs to find its interpreter and its shared libraries.
    assert env["PATH"] == "/usr/bin"


def test_sanitize_applies_the_reproducible_settings():
    env = python_env.sanitize({"PYTHONHASHSEED": "random", "PYTHONSAFEPATH": ""})

    assert env["PYTHONHASHSEED"] == "0"
    assert env["PYTHONSAFEPATH"] == "1"


def test_sanitize_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/somebody/elses/packages")
    monkeypatch.setenv("PYTHONHASHSEED", "random")

    assert python_env.sanitize() is os.environ

    assert "PYTHONPATH" not in os.environ
    assert os.environ["PYTHONHASHSEED"] == "0"


def test_importing_partcad_sanitized_this_process():
    """Nothing PartCAD spawns can inherit a PYTHON* variable it did not set."""
    assert pc.__version__  # the import that did it
    assert {name for name in os.environ if name.startswith("PYTHON")} <= set(python_env.PARTCAD_PYTHON_ENV)
    assert os.environ["PYTHONHASHSEED"] == "0"


def test_sandbox_interpreter_flags_isolate_without_isolated_mode(sandbox_python_flags):
    """'-I' is gone, but the half of it no environment variable can express is not."""
    flags = sandbox_python_flags

    assert flags == ["-sOOu"]
    assert "I" not in "".join(flags)


@pytest.mark.parametrize(
    "expression, expected",
    [
        # PYTHONHASHSEED is honored now, which is the whole point: under '-I' it
        # was ignored and this came back randomized.
        ("sys.flags.hash_randomization", "0"),
        # ... and the isolation '-I' used to provide is still in force.
        ("sys.flags.no_user_site", "1"),
        ("sys.flags.safe_path", "1"),
    ],
)
def test_a_child_of_this_process_starts_the_way_the_sandbox_expects(sandbox_python_flags, expression, expected):
    """What the sandbox actually gets: our flags, plus our sanitized environment.

    'safe_path' only exists on 3.11+; below that PYTHONSAFEPATH is ignored, as
    the '-P' flag it stands in for does not exist there either.
    """
    if expression == "sys.flags.safe_path" and sys.version_info < (3, 11):
        pytest.skip("PYTHONSAFEPATH requires Python 3.11")

    out = subprocess.run(
        [sys.executable, *sandbox_python_flags, "-c", "import sys; print(int(%s))" % expression],
        capture_output=True,
        text=True,
        check=True,
    )

    assert out.stdout.strip() == expected


def test_a_child_of_this_process_hashes_reproducibly(sandbox_python_flags):
    """The reason the seed is pinned: string iteration order stops moving."""
    script = "print(list({'CIRCLE', 'LWPOLYLINE', 'ARC', 'SPLINE', 'HATCH'}))"

    runs = {
        subprocess.run(
            [sys.executable, *sandbox_python_flags, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for _ in range(5)
    }

    assert len(runs) == 1
