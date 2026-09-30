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


def _runtime_for(tmp_path, version=None):
    """A real PythonRuntime, built for whichever sandbox version is asked for.

    Built through __init__, since the flags are what __init__ decides; the
    context only has to answer where the sandbox would live.
    """

    class _Ctx:
        user_config = types.SimpleNamespace(internal_state_dir=str(tmp_path))

    return PythonRuntime(_Ctx(), "none", version)


def _flags_for(tmp_path, version=None):
    """The flags a sandbox interpreter runs a wrapper with."""
    return _runtime_for(tmp_path, version).python_flags


def _provisioning_flags_for(tmp_path, version=None):
    """The flags a sandbox interpreter runs "-m venv"/"-m pip" with."""
    return _runtime_for(tmp_path, version).python_provisioning_flags


@pytest.fixture
def sandbox_python_flags(tmp_path):
    """The wrapper flags for a sandbox on the interpreter running these tests."""
    return _flags_for(tmp_path)


@pytest.fixture
def sandbox_provisioning_flags(tmp_path):
    """The provisioning flags for a sandbox on the interpreter running these tests."""
    return _provisioning_flags_for(tmp_path)


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


@pytest.mark.parametrize("version", ["3.11", "3.12", "3.13", "3.14"])
def test_sandbox_interpreter_flags_drop_isolated_mode_where_the_environment_can_replace_it(tmp_path, version):
    """'-I' is gone, but the half of it no environment variable can express is not.

    Where PYTHONSAFEPATH is honored it covers provisioning too, so both command
    kinds run with one and the same list.
    """
    flags = _flags_for(tmp_path, version)

    assert flags == ["-sOOu"]
    assert _provisioning_flags_for(tmp_path, version) == flags
    assert "I" not in "".join(flags)


@pytest.mark.parametrize("version", ["3.9", "3.10"])
def test_sandbox_interpreter_flags_keep_isolated_mode_where_only_provisioning_needs_it(tmp_path, version):
    """PYTHONSAFEPATH is ignored before 3.11, so there '-I' stands in for it.

    Only on the commands whose sys.path[0] is PartCAD's own working directory,
    which is the "-m" ones. A wrapper is run by path, so its sys.path[0] is the
    wrapper's directory and there is nothing for '-I' to keep out -- and
    charging it '-I' would cost it PYTHONHASHSEED, which '-E' ignores.
    """
    assert _provisioning_flags_for(tmp_path, version) == ["-sOOIu"]
    assert _flags_for(tmp_path, version) == ["-sOOu"]


def test_a_version_the_bound_cannot_read_isolates_the_old_way(tmp_path):
    """'pc init' writes ">=<host version>", and such a package has to keep working.

    Nothing between the schema and here trims that into a version this can
    compare, so it must not be the thing that discovers it -- and, since it
    cannot be shown to understand PYTHONSAFEPATH, its provisioning gets the
    isolation that needs no variable.
    """
    assert _provisioning_flags_for(tmp_path, ">=3.12") == ["-sOOIu"]
    assert _flags_for(tmp_path, ">=3.12") == ["-sOOu"]


@pytest.mark.parametrize(
    "cmd, provisioning",
    [
        (["-m", "venv", "--upgrade-deps", "/somewhere"], True),
        (["-m", "pip", "check"], True),
        (["/somewhere/wrapper_part_type.py", "/a/script.py", "/a/package"], False),
        ([], False),
    ],
)
def test_only_a_module_command_is_treated_as_provisioning(tmp_path, cmd, provisioning):
    """Which flags a command gets is read off the command, not off the caller."""
    runtime = _runtime_for(tmp_path, "3.10")
    expected = runtime.python_provisioning_flags if provisioning else runtime.python_flags

    assert runtime.flags_for(cmd) == expected


@pytest.mark.parametrize(
    "expression, expected",
    [
        # PYTHONHASHSEED is honored now, which is the whole point: under '-I' it
        # was ignored and this came back randomized. On every version, including
        # the ones whose provisioning still carries '-I'.
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


@pytest.mark.parametrize("module", ["venv", "pip"])
def test_a_shadowing_module_beside_the_sandbox_cannot_hijack_a_provisioning_command(
    tmp_path, sandbox_provisioning_flags, module
):
    """The reason 3.10 keeps '-I': provisioning runs "-m", and "-m" reads sys.path[0].

    Provisioning ("-m venv", "-m pip") inherits PartCAD's own working directory,
    and for a "-m" command Python puts that directory first on sys.path unless
    told otherwise. A file named after the module being run therefore wins over
    the module itself. On 3.11+ PYTHONSAFEPATH is what says otherwise; below it
    only "-I" does -- so this asserts the outcome, on whichever interpreter is
    running the tests, rather than the mechanism that produced it.
    """
    (tmp_path / (module + ".py")).write_text("print('SHADOWED')\n")

    out = subprocess.run(
        [sys.executable, *sandbox_provisioning_flags, "-m", module, "--help"],
        cwd=str(tmp_path),
        env=os.environ,
        capture_output=True,
        text=True,
    )

    assert "SHADOWED" not in out.stdout, out.stdout


def test_a_file_beside_partcad_cannot_hijack_a_module_a_wrapper_imports(tmp_path, sandbox_python_flags):
    """And the reason a wrapper does not need '-I': it is run by path, not by "-m".

    A wrapper reaches its siblings the way every wrapper in 'wrappers/' does --
    by appending its own directory to sys.path -- so what it imports comes from
    PartCAD's own directory. PartCAD's working directory, which is the one a
    user can drop files into, is on sys.path for neither branch: below 3.11 it
    is the script's directory that leads instead, and at 3.11+ PYTHONSAFEPATH
    leaves the front of sys.path empty.
    """
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    (wrappers / "sibling.py").write_text("ORIGIN = 'WRAPPER'\n")
    (wrappers / "wrapper.py").write_text("""import os
import sys

sys.path.append(os.path.dirname(__file__))
import sibling

print(sibling.ORIGIN)
""")

    working_directory = tmp_path / "cwd"
    working_directory.mkdir()
    (working_directory / "sibling.py").write_text("ORIGIN = 'SHADOWED'\n")

    out = subprocess.run(
        [sys.executable, *sandbox_python_flags, str(wrappers / "wrapper.py")],
        cwd=str(working_directory),
        env=os.environ,
        capture_output=True,
        text=True,
        check=True,
    )

    assert out.stdout.strip() == "WRAPPER"
