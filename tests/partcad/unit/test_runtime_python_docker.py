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
import pathlib
import types

import docker
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
    workflow = (pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml").read_text()
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


# --------------------------------------------------------------------------- #
# Reusing a container                                                          #
# --------------------------------------------------------------------------- #


class _Container:
    """A container that was started with some set of mounts."""

    def __init__(self, sources, status="running"):
        self.attrs = {"Mounts": [{"Source": source} for source in sources]}
        self.status = status
        self.removed = False
        self.started = False

    def start(self):
        self.started = True

    def remove(self, force=False):
        self.removed = True


class _Client:
    def __init__(self, existing=None):
        self.existing = existing
        self.made = None
        self.images = types.SimpleNamespace(get=lambda name: name, pull=lambda name: name)
        self.containers = types.SimpleNamespace(get=self._get, run=self._run)

    def _get(self, name):
        import docker

        if self.existing is None:
            raise docker.errors.NotFound(name)
        return self.existing

    def _run(self, image, **kwargs):
        self.made = kwargs
        return _Container(kwargs.get("volumes") or {})


def _started(tmp_path, monkeypatch, existing):
    made = _runtime(tmp_path)
    client = _Client(existing)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)
    return made, client, made._start()


def test_a_container_that_can_see_this_context_is_reused(tmp_path, monkeypatch):
    made = _runtime(tmp_path)
    wanted = docker_mount.mounts(made._mounted)
    existing = _Container(wanted, status="exited")

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is existing
    assert existing.started is True
    assert client.made is None


def test_a_container_that_cannot_is_replaced(tmp_path, monkeypatch):
    """The name says which image and nothing about what is mounted.

    The context root is mounted too, and that is per package -- so a container
    started while working on one package cannot serve another, and reusing it
    made every command naming a file under the second root fail on a path that
    is not there.
    """
    existing = _Container(["/somewhere/else"])

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is not existing
    assert existing.removed is True
    assert client.made is not None


# --------------------------------------------------------------------------- #
# Knowing the environment is there                                             #
# --------------------------------------------------------------------------- #


def test_a_dangling_interpreter_symlink_still_counts_as_built(tmp_path):
    """Which is what a virtual environment built in a container looks like here.

    'bin/python' points at the interpreter that built it -- the image's, at a
    path this machine has no file for. Following the symlink asks whether the
    host can *run* it, and the answer is no and always will be; the question is
    whether the environment is there.
    """
    made = _runtime(tmp_path)
    os.makedirs(os.path.dirname(made._host_venv_python))
    # Standing in for the image's own interpreter -- '/usr/local/bin/python3' in
    # a `python:*-slim`. Named under 'tmp_path' rather than there because a
    # machine that happens to have that file (this dev container does; a GitHub
    # runner does not) would not be testing anything.
    os.symlink(str(tmp_path / "only-inside-the-image" / "python3"), made._host_venv_python)

    assert os.path.exists(made._host_venv_python) is False, "the premise: the target is not here"
    assert made._environment_built is True
    # And so it is not built again, which is what turned a good build into a
    # failure every time.
    assert made._create_locked() == []


def test_no_environment_is_not_built(tmp_path):
    assert _runtime(tmp_path)._environment_built is False


# --------------------------------------------------------------------------- #
# Getting hold of the image                                                    #
# --------------------------------------------------------------------------- #
#
# 'resolve_image' is the one place that talks to a registry, and the whole of
# its job is to try the architecture-suffixed name before the bare one and to
# say something useful when neither can be had. None of that needs a daemon --
# it needs a client that answers -- so it is pinned here rather than left to the
# integration legs.


class _Registry:
    """A docker client that holds some images and can be asked to pull others."""

    def __init__(self, local=(), pullable=()):
        self.local = set(local)
        self.pullable = set(pullable)
        self.pulled = []

        def get(name):
            if name not in self.local:
                raise docker.errors.ImageNotFound(name)
            return types.SimpleNamespace(tags=[name])

        def pull(name):
            if name not in self.pullable:
                raise docker.errors.NotFound("no such image: %s" % name)
            self.pulled.append(name)
            self.local.add(name)
            return types.SimpleNamespace(tags=[name])

        self.images = types.SimpleNamespace(get=get, pull=pull)


def test_an_image_already_here_is_not_pulled():
    """Which is what lets somebody test with an image they built by hand."""
    wanted = "ghcr.io/x/solver:1"
    client = _Registry(local=runtime_python_docker.docker_image.candidates(wanted)[:1])

    resolved = runtime_python_docker.resolve_image(client, wanted)

    assert resolved == runtime_python_docker.docker_image.candidates(wanted)[0]
    assert client.pulled == []


def test_the_architecture_suffixed_name_is_preferred_over_the_bare_one():
    wanted = "ghcr.io/x/solver:1"
    suffixed, bare = runtime_python_docker.docker_image.candidates(wanted)[:2]
    client = _Registry(local=[suffixed, bare])

    assert runtime_python_docker.resolve_image(client, wanted) == suffixed


def test_an_image_that_is_not_here_is_pulled():
    wanted = "ghcr.io/x/solver:1"
    suffixed = runtime_python_docker.docker_image.candidates(wanted)[0]
    client = _Registry(pullable=[suffixed])

    assert runtime_python_docker.resolve_image(client, wanted) == suffixed
    assert client.pulled == [suffixed]


def test_the_bare_name_is_pulled_when_no_architecture_tag_is_published():
    """The common case for a third-party image built for one architecture."""
    wanted = "ghcr.io/x/solver:1"
    candidates = runtime_python_docker.docker_image.candidates(wanted)
    bare = candidates[-1]
    client = _Registry(pullable=[bare])

    assert runtime_python_docker.resolve_image(client, wanted) == bare


def test_an_image_nobody_can_get_names_every_name_it_tried():
    """The error is the only thing the user has to work out what to publish."""
    wanted = "ghcr.io/x/solver:1"
    client = _Registry()

    with pytest.raises(runtime.SandboxUnavailable) as raised:
        runtime_python_docker.resolve_image(client, wanted)

    for name in runtime_python_docker.docker_image.candidates(wanted):
        assert name in str(raised.value)


# --------------------------------------------------------------------------- #
# Asking early whether it would work                                           #
# --------------------------------------------------------------------------- #
#
# A daemon answering says a container could be started; it says nothing about
# whether the image to start it from can be reached. 'image_available' is what
# turns that into one question 'pc test' can ask before it commits to a sandbox.


def test_an_image_is_unavailable_without_a_container_runtime(monkeypatch):
    monkeypatch.setattr(runtime_python_docker.runtime, "docker_available", lambda: False)
    monkeypatch.setattr(
        runtime_python_docker.docker, "from_env", lambda *a, **k: pytest.fail("asked the daemon after finding none")
    )

    assert runtime_python_docker.image_available("ghcr.io/x/solver:1") is False


def test_an_image_is_unavailable_when_the_client_cannot_be_made(monkeypatch):
    """'docker_available' passed and connecting still failed -- it can happen
    between the two, and a raised exception here is not this caller's answer."""
    monkeypatch.setattr(runtime_python_docker.runtime, "docker_available", lambda: True)

    def refuse(*a, **k):
        raise RuntimeError("daemon went away")

    monkeypatch.setattr(runtime_python_docker.docker, "from_env", refuse)

    assert runtime_python_docker.image_available("ghcr.io/x/solver:1") is False


def test_an_image_that_resolves_is_available(monkeypatch):
    wanted = "ghcr.io/x/solver:1"
    client = _Registry(local=runtime_python_docker.docker_image.candidates(wanted)[:1])
    monkeypatch.setattr(runtime_python_docker.runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda *a, **k: client)

    assert runtime_python_docker.image_available(wanted) is True


def test_an_image_that_cannot_be_reached_is_unavailable(monkeypatch):
    """A failure asked for early, rather than found halfway through a render."""
    monkeypatch.setattr(runtime_python_docker.runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda *a, **k: _Registry())

    assert runtime_python_docker.image_available("ghcr.io/x/solver:1") is False


# --------------------------------------------------------------------------- #
# A sandbox that did not get built                                             #
# --------------------------------------------------------------------------- #


def test_a_failed_environment_says_what_went_wrong(tmp_path):
    """'run_*_locked' reports an exit code rather than raising.

    Without this the first thing anybody saw was pip failing on a missing file,
    several steps after the thing that actually broke.
    """
    made = _runtime(tmp_path)

    with pytest.raises(Exception, match="no space left on device"):
        made._created(1, "no space left on device")


def test_a_failed_environment_with_nothing_on_stderr_still_says_the_exit_code(tmp_path):
    made = _runtime(tmp_path)

    with pytest.raises(Exception, match="exited with 3"):
        made._created(3, "")
