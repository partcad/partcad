#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The sandbox whose interpreter lives in a container.

Nothing here starts one. What is worth pinning without a container runtime is
the part that decides *what* would be started and *how* a command reaches it --
the sandbox's identity, the command line, and the two places where the host
being Windows changes the answer. Actually running an interpreter over there is
the job of the integration legs in CI, which have a Docker daemon.
"""

import os
import types

import pytest

from partcad import docker_mount, runtime, runtime_python_docker


def _ctx(tmp_path):
    """The little of a context this runtime reads."""
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state")),
        root_path=str(tmp_path / "pkg"),
    )


def _runtime(tmp_path, image="ghcr.io/x/solver:abc", version="3.11"):
    return runtime_python_docker.DockerPythonRuntime(_ctx(tmp_path), version, image=image)


# --------------------------------------------------------------------------- #
# What the sandbox is                                                          #
# --------------------------------------------------------------------------- #


def test_the_base_image_is_named_by_release_and_version():
    assert (
        runtime_python_docker.image_for("3.11", release="0.8.58")
        == "ghcr.io/partcad/partcad-container-python:0.8.58-py3.11"
    )


def test_the_base_image_is_the_one_ci_publishes():
    """Two places name it, and a name that drifts is a sandbox that pulls nothing.

    The workflow builds `<registry>/<repository>-container-python` and tags it
    `<release>-py<version>-<arch>`; `image_for()` asks for the same thing minus
    the architecture, which `docker_image.candidates()` appends.
    """
    workflow = open(".github/workflows/test.yml").read()
    assert "${{ github.repository }}-container-python" in workflow
    assert runtime_python_docker.BASE_IMAGE == "ghcr.io/partcad/partcad-container-python"
    assert "${PC_VERSION}-py${PY}-${ARCH}" in workflow


def test_two_images_are_two_sandboxes(tmp_path):
    """What pip resolves depends on the native libraries under it.

    Two images at one Python version therefore install different things, and a
    shared directory would leave each finding the other's builds.
    """
    one = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:def")
    assert one.path != two.path
    assert one.container_name != two.container_name


def test_the_same_image_is_the_same_sandbox(tmp_path):
    """So that two packages naming one image share a container rather than starting two."""
    one = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    assert one.path == two.path
    assert one.container_name == two.container_name


def test_the_sandbox_directory_says_which_sandbox_it_is(tmp_path):
    """'pc-' and the method are what somebody reads in a file browser."""
    made = _runtime(tmp_path)
    assert os.path.basename(made.path).startswith("pc-py-docker-")
    assert made.path.endswith("-3.11")


# --------------------------------------------------------------------------- #
# How a command gets there                                                     #
# --------------------------------------------------------------------------- #


def test_a_command_runs_through_docker_exec(tmp_path, monkeypatch):
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    assert made._exec(["/some/python", "-m", "pip", "install", "numpy"]) == [
        "docker",
        "exec",
        "-i",
        made.container_name,
        "/some/python",
        "-m",
        "pip",
        "install",
        "numpy",
    ]


def test_a_working_directory_becomes_an_argument_of_docker(tmp_path, monkeypatch):
    """Not of the 'docker' process itself, which runs wherever PartCAD is."""
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    argv = made._exec(["/some/python"], cwd="/work/pkg")
    assert argv[:5] == ["docker", "exec", "-i", "-w", "/work/pkg"]


def test_stdin_reaches_the_interpreter(tmp_path, monkeypatch):
    """'-i' is what makes that true, and a wrapper is driven entirely by stdin."""
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)
    assert "-i" in made._exec(["/some/python"])


# --------------------------------------------------------------------------- #
# Where the host being Windows changes the answer                              #
# --------------------------------------------------------------------------- #


def test_the_environment_interpreter_is_a_posix_path_on_a_windows_host(tmp_path, monkeypatch):
    """The environment was built by Linux; the host reading it does not change that.

    The base class looks in 'Scripts' and for 'python.exe' when 'os.name' is
    'nt', which is the right answer for an environment on the host and the
    wrong one for this.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(docker_mount.os, "name", "nt")

    session = {"dirty": True, "path": r"C:\Users\you\.partcad\sandbox\v-env-abc", "name": "abc"}
    assert made.get_venv_python_path(session) == "/c/Users/you/.partcad/sandbox/v-env-abc/bin/python"


def test_the_interpreter_name_has_no_exe_suffix(tmp_path):
    """'exec_name' is what the base class joins onto an environment path."""
    assert _runtime(tmp_path).exec_name == "python"


# --------------------------------------------------------------------------- #
# Saying so when there is no container runtime                                 #
# --------------------------------------------------------------------------- #


def test_no_container_runtime_is_reported_as_the_sandbox_being_unavailable(tmp_path, monkeypatch):
    """Not as a failure of whatever asked for it.

    'SandboxUnavailable' is the type callers already catch to tell "this machine
    cannot" from "this package cannot", and the sentence says which knob fixes
    it.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "docker_available", lambda: False)

    with pytest.raises(runtime.SandboxUnavailable, match="pythonSandbox"):
        made._start()


# --------------------------------------------------------------------------- #
# Which seam the container is behind                                           #
# --------------------------------------------------------------------------- #


def test_the_launch_is_what_is_wrapped(tmp_path, monkeypatch):
    """Not a 'run' method, because there is more than one launch point.

    'PythonRuntime' launches an interpreter from two places -- once directly
    and once through 'Runtime.run' -- and a sandbox that replaced one of them
    ran the other on the host: the environment this sandbox is supposed to
    build inside the container was built by whichever interpreter PartCAD
    itself was running under.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    argv, cwd, env = made._spawn(["/some/python", "-c", "pass"], cwd="/work", env={"PATH": "/nowhere"})

    assert argv[:3] == ["docker", "exec", "-i"]
    assert argv[-3:] == ["/some/python", "-c", "pass"]
    # The directory belongs to the container, so it becomes a flag of 'docker'
    # rather than the directory 'docker' itself is run in; the environment
    # belongs to the interpreter, and putting it on the client would be the
    # opposite of the intent.
    assert "-w" in argv
    assert cwd is None
    assert env is None


def test_the_way_a_part_is_run_is_a_call_this_sandbox_accepts(tmp_path, monkeypatch):
    """'part_factory_wrapper' calls 'run_async(cmd, stdin, session=...)'.

    A sandbox with methods of its own shape refused that call before any
    container was involved -- so the sandbox could not render a single part,
    while every test about it passed. Made as the call rather than as a look at
    the signature, because the signature is a telemetry wrapper's.
    """
    import asyncio
    import sys

    made = _runtime(tmp_path)
    made.provisioned = True
    made.exec_path = sys.executable
    monkeypatch.setattr(
        made, "_spawn", lambda cmd, cwd=None, env=None: ([sys.executable, "-c", "print('ran')"], None, None)
    )

    exitcode, stdout, stderr = made.run(["-c", "pass"], "", session=None)
    assert exitcode == 0, stderr
    assert "ran" in stdout

    exitcode, stdout, stderr = asyncio.run(made.run_async(["-c", "pass"], "", session=None))
    assert exitcode == 0, stderr
    assert "ran" in stdout


def test_the_environment_is_built_over_there(tmp_path, monkeypatch):
    """'-m venv' is the first thing this sandbox runs, and the easiest to lose.

    It leaves a directory that looks exactly like a working sandbox whichever
    machine built it, so nothing downstream notices that the interpreter inside
    it is the host's.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    argv, _, _ = made._spawn(["/some/python"] + made._create_locked())

    assert argv[:2] == ["docker", "exec"]
    assert "venv" in argv
