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

import inspect
import os
import pathlib
import platform
import tempfile
import time
import types

import docker
import pytest

from partcad import docker_mount, output, runtime, runtime_python_docker, wrapper


def _ctx(tmp_path):
    """The little of a context this runtime reads."""
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state")),
        root_path=str(tmp_path / "pkg"),
        sandbox_paths=[],
    )


def _runtime(tmp_path, image="ghcr.io/x/solver:abc", version="3.11"):
    return runtime_python_docker.DockerPythonRuntime(_ctx(tmp_path), version, image=image)


class _WindowsOs:
    """The real 'os', except that it says 'nt'.

    'os.name' cannot be set for one module: every module that imported 'os'
    imported the same object, so setting it there sets it for 'pathlib' too --
    which then hands out 'WindowsPath' objects it cannot instantiate on this
    host. What that looks like is not an assertion failing: it is the suite
    dying inside pytest's own path handling while it formats the report, with
    nothing naming the test that did it.

    So a module that has to believe it is on Windows is given one of these
    instead of the module, and everything it reads from 'os' other than the
    name is the real thing.
    """

    name = "nt"

    def __getattr__(self, attribute):
        return getattr(os, attribute)


# --------------------------------------------------------------------------- #
# What the sandbox is                                                          #
# --------------------------------------------------------------------------- #


def test_the_base_image_is_named_by_release_and_version(no_image_tag_override):
    """The name an installed PartCAD asks for, which is the release and nothing else.

    `no_image_tag_override` because a run that rebuilt these images points every
    reader at its own tag, this suite included -- so without it this asserted
    the release on a developer machine and the branch tag in CI.
    """
    assert (
        runtime_python_docker.image_for("3.11", release="0.8.58")
        == "ghcr.io/partcad/partcad-container-python:0.8.58-py3.11"
    )


def test_the_base_image_is_the_one_ci_publishes():
    """Two places name it, and a name that drifts is a sandbox that pulls nothing.

    The workflow builds `<registry>/<repository>-container-python` and tags it
    `<tag>-py<version>-<arch>`; `image_for()` asks for the same thing minus the
    architecture, which `docker_image.candidates()` appends.

    `<tag>` is the release on an ordinary run, and a run that rebuilt these
    images addresses them by one of its own -- which is why both sides go
    through `container_image.image_tag` rather than writing the release
    directly. See `tests/dev_tools/test_container_images.py`.
    """
    workflow = (pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml").read_text()
    assert "${{ github.repository }}-container-python" in workflow
    assert runtime_python_docker.BASE_IMAGE == "ghcr.io/partcad/partcad-container-python"
    assert 'PC_IMAGE_REF="${IMAGE}:${IMAGE_TAG}-py${PY}-${ARCH}"' in workflow
    assert "container_image.image_tag(release)" in inspect.getsource(runtime_python_docker)


def _build_containers_steps():
    """The steps of the job that builds and publishes the base images."""
    import yaml

    workflow = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "test.yml"
    return yaml.safe_load(workflow.read_text())["jobs"]["build-containers"]["steps"]


def _step(name):
    for step in _build_containers_steps():
        if step.get("name") == name:
            return step
    raise AssertionError("no step named %r in 'build-containers'" % name)


def test_the_version_tag_is_published_once_by_the_version_bump():
    """Which is the whole of what makes it a tag a package may pin.

    It used to be pushed by every event that was not a pull request or a merge
    queue run -- so the nightly rewrote it, daily, with whatever 'devel' held at
    the time. A pin that moves under the package that took it is not a pin, and
    the comment beside it had called it immutable throughout.

    The condition itself is no longer written here. It moved into
    `.github/actions/container-images`, which answers the same question for the
    KiCad image and for `CI-Dev`, and which is where the rule is now pinned
    (`tests/dev_tools/test_container_images.py`): a version bump or a dispatch
    publishes the release tag, a run that rebuilt the images publishes one of
    its own, and nothing else publishes at all. What this asserts is the half
    that lives in this workflow -- that the step takes both the tag and the
    permission from that one answer, rather than deciding either for itself.
    A second copy here is how the two would come to disagree, and a build under
    one tag with permission granted for another is precisely the release tag
    being overwritten from a branch.
    """
    step = _step("Build the Python sandbox images")

    assert step["env"]["PUSH"] == "${{ needs.set-matrix.outputs.image-push }}"
    assert step["env"]["IMAGE_TAG"] == "${{ needs.set-matrix.outputs.image-tag }}"
    # The release still goes *into* the image, whatever the image is called.
    assert step["env"]["PC_VERSION"] == "${{ needs.set-matrix.outputs.image-release }}"
    assert 'PC_PARTCAD_VERSION="${PC_VERSION}"' in step["run"]


def test_the_moving_tag_is_not_written_by_a_build():
    """A plugin builds 'FROM' it, so what it names has to be what was tested.

    The Dockerfile does not change between the bump and the release; 'apt-get'
    and 'pip' do, because they resolve against the day they run. So the release
    below retags rather than rebuilds, and the build here must not write this
    tag at all -- it appears only as a cache source.
    """
    run = _step("Build the Python sandbox images")["run"]

    assert 'PC_IMAGE_REF="${IMAGE}:py${PY}-${ARCH}"' not in run
    # It is the cache source and only the cache source. The `type=registry,ref=`
    # around it is `dev-tools/ci/build-sandbox-image.sh`'s to write now, this
    # step naming the image the layers come from.
    assert 'PC_CACHE_FROM="${IMAGE}:py${PY}-${ARCH}"' in run


def test_the_release_advances_the_moving_tag_without_rebuilding():
    """'main' is where a published version becomes the released one.

    A rebuild would produce an image nothing had tested and hand it to every
    plugin author; 'imagetools create' copies the manifest, so the moving tag
    and the version tag name the same bytes.
    """
    step = _step("Release the Python sandbox images")

    assert "refs/heads/main" in step["if"]
    assert "Version updated" in step["if"]
    assert "imagetools create" in step["run"]
    # The trailing space is what keeps this from matching the "docker buildx"
    # of "imagetools create" itself.
    assert "docker build " not in step["run"]
    assert "buildx build" not in step["run"]
    # Pointed at the version this run carries, which is what "devel" published.
    assert '"${IMAGE}:${PC_VERSION}-py${PY}-${ARCH}"' in step["run"]


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


def test_one_container_serves_every_context(tmp_path):
    """The name says which image and nothing else, so it outlives the process.

    It was briefly named after the mounts too, which made a container that no
    other context could reuse -- and reuse across contexts and across runs is
    the whole reason to keep one warm. Contexts differing in what they mount
    share it; whichever of them starts it, the next one finds it running.
    """
    one = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two.ctx.sandbox_paths = [str(tmp_path / "somebody-elses-files")]

    assert one.container_name == two.container_name


def test_a_new_image_tag_is_a_new_container(tmp_path):
    """Which is the one thing that should make it a different container."""
    one = _runtime(tmp_path, image="ghcr.io/x/solver:0.8.61")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:0.8.62")

    assert one.container_name != two.container_name


def test_the_sandbox_directory_says_which_sandbox_it_is(tmp_path):
    """'pc-' and the method are what somebody reads in a file browser."""
    made = _runtime(tmp_path)
    assert os.path.basename(made.path).startswith("pc-py-docker-")
    assert made.path.endswith("-3.11")


# --------------------------------------------------------------------------- #
# What the container can see                                                   #
# --------------------------------------------------------------------------- #


def _reachable(made, path) -> bool:
    """Whether the container could open ``path``: it is under one of the mounts."""
    return any(docker_mount.contains(mount, path) for mount in docker_mount.mounts(made._mounted))


def test_a_wrapper_is_reachable_from_inside_the_container(tmp_path):
    """The sandbox interpreter is handed the wrappers by path and has to open them.

    A checkout with its virtual environment inside the package it is working on
    got this for free, which is what hid it; the frozen bundle, whose files sit
    next to the executable, never did, and rendering through this sandbox died
    on "can't open file '.../_internal/partcad/wrappers/wrapper_plugin.py'".

    Asserted of the path the rest of PartCAD actually builds, rather than of the
    mount, so that a wrapper moving out from under it is this test failing.
    """
    made = _runtime(tmp_path)
    assert _reachable(made, wrapper.get("plugin.py"))


def test_a_builtin_package_is_reachable_from_inside_the_container(tmp_path):
    """The other thing PartCAD ships inside itself and executes by path.

    It sits beside the wrappers, which is why one mount covers both -- but
    "beside" is a fact about the tree rather than a rule, so ask directly.
    """
    made = _runtime(tmp_path)
    assert _reachable(made, output.BUILTIN_ROOT_PATH)


def test_a_path_the_context_named_is_mounted_too(tmp_path):
    """An ad-hoc command's input and output, which are nowhere near its package.

    'pc adhoc convert' generates its package in one temporary directory and
    points it at the user's file wherever that is, so neither the input nor the
    output is under the context root. A sandbox on the host does not care; this
    one sees only what is mounted, and without this the wrapper reported that it
    could not read a file the user can see perfectly well
    ("Failed to read the STL file").
    """
    made = _runtime(tmp_path)
    made.ctx.sandbox_paths = [str(tmp_path / "elsewhere")]

    assert _reachable(made, str(tmp_path / "elsewhere" / "cube.stl"))


def test_a_context_names_the_home_directory_and_the_usual_three(tmp_path):
    """Which is every context but an ad-hoc one.

    The home directory leads because on an ordinary machine it contains the
    other three, and 'mounts' then drops them -- see the test below. Here they
    are under 'tmp_path' instead, so all four survive and the list is the whole
    set this asks for.
    """
    made = _runtime(tmp_path)

    assert sorted(made._mounted) == sorted(
        [
            os.path.expanduser("~"),
            tempfile.gettempdir(),
            made.ctx.user_config.internal_state_dir,
            runtime_python_docker.INSTALL_DIR,
            made.ctx.root_path,
        ]
    )


def _one_big_directory(tmp_path, monkeypatch):
    """Put the home directory and the temporary one under 'tmp_path'.

    Both are read from the platform, and neither is steerable by the lever you
    would reach for first: 'HOME' is ignored on Windows, where 'expanduser'
    reads 'USERPROFILE', and the temporary directory is under the profile there
    but under '/var/folders' on macOS. A test that set 'HOME' and hoped
    therefore passed on Linux, passed on Windows by accident -- the profile
    happened to contain pytest's 'tmp_path' -- and would have failed on macOS,
    where neither contains the other.

    So both are stated outright, and the test says the same thing everywhere.
    """
    monkeypatch.setattr(runtime_python_docker.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    monkeypatch.setattr(runtime_python_docker.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setattr(runtime_python_docker, "INSTALL_DIR", str(tmp_path / "lib" / "partcad"))


def test_everything_under_one_directory_is_one_mount(tmp_path, monkeypatch):
    """The case worth having, and the reason the home directory is named at all.

    '~/.partcad', the package and the installation are all under '~' on an
    ordinary machine, so they collapse into it. Here the temporary directory is
    put under it as well, which is true on Windows and not on Linux or macOS --
    so this is the best case rather than the common one, and what it pins is
    that nesting collapses rather than how many mounts a given platform ends up
    with.
    """
    _one_big_directory(tmp_path, monkeypatch)
    made = _runtime(tmp_path)
    made.ctx.sandbox_paths = [str(tmp_path / "models")]

    assert docker_mount.mounts(made._mounted) == {
        str(tmp_path): {"bind": docker_mount.translate(str(tmp_path)), "mode": "rw"}
    }


def test_everything_is_writable(tmp_path):
    """Mounting the installation read-only was tried and taken back out.

    It is one more thing that can differ between two containers of one image,
    on a contract that is a stopgap for the paths a wrapper is handed rather
    than the isolation boundary. The container is that.
    """
    made = _runtime(tmp_path)

    assert {spec["mode"] for spec in docker_mount.mounts(made._mounted).values()} == {"rw"}


def test_a_wrapper_path_is_rewritten_on_a_windows_host(tmp_path, monkeypatch):
    """Which the installation being one of the mounts is what makes possible.

    'rewrite' only knows the mounts it is handed, so on Windows an installation
    that is not one of them is not merely unreachable -- it is handed to the
    container spelled 'C:\\...', which is not a path over there at all.
    """
    install = "C:\\Program Files\\PartCAD\\_internal\\partcad"
    monkeypatch.setattr(runtime_python_docker, "INSTALL_DIR", install)
    made = _runtime(tmp_path)

    # What '_exec' does to every argument, with 'windows' stated outright.
    # The parameter exists for this: nothing has to be made to believe it is on
    # Windows, so nothing has to be put back afterwards.
    rewritten = docker_mount.rewrite(install + "\\wrappers\\wrapper_plugin.py", made._mounted, windows=True)

    assert rewritten == "/c/Program Files/PartCAD/_internal/partcad/wrappers/wrapper_plugin.py"


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
        "-e",
        "HOME=" + docker_mount.rewrite(made._container_home, made._mounted),
        made.container_name,
        "/some/python",
        "-m",
        "pip",
        "install",
        "numpy",
    ]


def test_the_container_is_given_a_home_it_can_write_to(tmp_path, monkeypatch):
    """Docker sets 'HOME=/' for a uid with no passwd entry, and '/' is root's.

    PartCAD runs the container as the host's own uid on Linux, so that is every
    Linux host. Everything that caches under '~/.cache' then fails to make one,
    and 'ezdxf' says so on stderr -- which PartCAD reports as the wrapper having
    failed, so every render in a container came back as an error.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    argv = made._exec(["/some/python"])
    home = argv[argv.index("-e") + 1]

    # The container's view of it, not the host's. Identical on a POSIX host,
    # which is why writing the host path here passed everywhere except Windows
    # -- and there it asserted that PartCAD hands the container a path the
    # container has no such name for.
    assert home == "HOME=" + docker_mount.rewrite(made._container_home, made._mounted)
    # Under the state directory, which is mounted, writable, and outlives the
    # container -- a cache written there is one the next run still has.
    assert made._container_home.startswith(made.ctx.user_config.internal_state_dir)


def test_the_home_it_is_given_is_the_container_s_path(tmp_path, monkeypatch):
    """Stated on Windows, where the two differ, and not left to the platform.

    'HOME' is handed to a Linux process inside the container, so it has to be
    the mapped path. On a POSIX host 'rewrite' is the identity, so a test that
    built the expected value out of the host path agreed with a correct
    implementation and with a broken one alike -- and said so only on the
    platform CI is slowest to hear from.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)
    monkeypatch.setattr(
        made.__class__,
        "_container_home",
        property(lambda self: "C:\\Users\\you\\.partcad\\container-home"),
    )
    monkeypatch.setattr(made.__class__, "_mounted", property(lambda self: ["C:\\Users\\you\\.partcad"]))
    # Only what 'docker_mount' reads, and only inside it. Setting 'os.name'
    # globally makes 'pathlib' hand out 'WindowsPath' objects it cannot
    # instantiate here, and the suite dies in pytest's own cleanup rather than
    # in this assertion.
    monkeypatch.setattr(docker_mount, "os", _WindowsOs())

    argv = made._exec(["/some/python"])

    assert argv[argv.index("-e") + 1] == "HOME=/c/Users/you/.partcad/container-home"


def test_a_working_directory_becomes_an_argument_of_docker(tmp_path, monkeypatch):
    """Not of the 'docker' process itself, which runs wherever PartCAD is."""
    made = _runtime(tmp_path)
    monkeypatch.setattr(made, "_start", lambda: None)

    argv = made._exec(["/some/python"], cwd="/work/pkg")
    assert argv[:3] == ["docker", "exec", "-i"]
    assert argv[argv.index("-w") + 1] == "/work/pkg"
    # Before the container name, which is where 'docker exec' stops taking
    # options -- anything after it belongs to the command being run.
    assert argv.index("-w") < argv.index(made.container_name)


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
    # Both modules that read the name, and neither of them globally: see
    # '_WindowsOs'. This test used to set 'os.name' itself, which is the same
    # object 'pathlib' reads.
    monkeypatch.setattr(runtime_python_docker, "os", _WindowsOs())
    monkeypatch.setattr(docker_mount, "os", _WindowsOs())

    session = {"dirty": True, "path": r"C:\Users\you\.partcad\sandbox\v-env-abc", "name": "abc"}
    assert made.get_venv_python_path(session) == "/c/Users/you/.partcad/sandbox/v-env-abc/bin/python"


def test_the_interpreter_name_has_no_exe_suffix(tmp_path):
    """'exec_name' is what the base class joins onto an environment path."""
    assert _runtime(tmp_path).exec_name == "python"


# --------------------------------------------------------------------------- #
# Saying so when the daemon is not on this filesystem                          #
# --------------------------------------------------------------------------- #


class _ProbeClient:
    """A daemon that answers the mount probe one way or the other.

    'sees' says whether the container it runs finds the file the probe wrote,
    which is the whole question: a daemon outside this filesystem binds a
    directory of the same name from somewhere else, and Docker creates it empty.
    """

    def __init__(self, sees=True, base_url="http+docker://localhost"):
        self.sees = sees
        self.runs = []
        self.api = types.SimpleNamespace(base_url=base_url)
        self.images = types.SimpleNamespace(get=lambda name: name, pull=lambda name: name)
        self.containers = types.SimpleNamespace(get=self._get, run=self._run)

    def _get(self, name):
        raise docker.errors.NotFound(name)

    def _run(self, image, **kwargs):
        self.runs.append((image, kwargs))
        if self.sees:
            return b""
        raise docker.errors.ContainerError(
            container="probe", exit_status=1, command=kwargs.get("command"), image=image, stderr=b""
        )


@pytest.fixture(autouse=True)
def _forget_the_probe():
    """Its answer is cached for the process, which two tests must not share."""
    runtime_python_docker._MOUNTS_SHARED.clear()
    yield
    runtime_python_docker._MOUNTS_SHARED.clear()


def test_a_daemon_that_sees_this_filesystem_can_run_the_sandbox(tmp_path):
    """The ordinary case: the probe file is written here and read over there."""
    client = _ProbeClient(sees=True)

    assert runtime_python_docker.mounts_are_shared(client, "some/image:tag") is True


def test_a_daemon_somewhere_else_cannot(tmp_path):
    """Docker outside of Docker, or a 'DOCKER_HOST' on another machine.

    The container starts and the mount is made; it is simply a mount of a
    different directory, which nothing about the run says. So the probe writes a
    file and asks whether it is there.
    """
    client = _ProbeClient(sees=False)

    assert runtime_python_docker.mounts_are_shared(client, "some/image:tag") is False


def test_the_probe_looks_for_the_file_it_wrote_in_the_directory_it_mounted(tmp_path):
    """And mounts exactly one directory: the temporary one it just made.

    Asserted because a probe that mounted something else, or looked somewhere
    else, would answer for a directory nobody is going to use -- and would say
    "shared" on a machine where nothing is.
    """
    client = _ProbeClient(sees=True)

    runtime_python_docker.mounts_are_shared(client, "some/image:tag")

    _image, kwargs = client.runs[0]
    (mounted,) = kwargs["volumes"]
    assert runtime_python_docker._PROBE_FILE in kwargs["command"][-1]
    assert docker_mount.translate(mounted) in kwargs["command"][-1]
    # Thrown away with the answer. A probe that left containers behind would be
    # one per process on every machine PartCAD runs on.
    assert kwargs["remove"] is True
    # And run as the user who made the file, on the platform where that is what
    # decides whether it can be read back. A temporary directory belongs to the
    # host user and to nobody else, so a probe running as the image's user reads
    # nothing, calls a daemon that is right here "somewhere else", and turns the
    # sandbox off on every machine whose uid is not the image's -- which is every
    # GitHub runner.
    if platform.system() == "Linux":
        assert kwargs["user"] == "%d:%d" % (os.getuid(), os.getgid())
    else:
        assert kwargs["user"] is None


def test_the_daemon_is_asked_once(tmp_path):
    """It is a property of how this machine reaches Docker, not of the moment.

    A container per part -- which is what asking per sandbox would be -- is a
    cost on every machine to answer a question whose answer never changes.
    """
    client = _ProbeClient(sees=True)

    runtime_python_docker.mounts_are_shared(client, "some/image:tag")
    runtime_python_docker.mounts_are_shared(client, "some/image:tag")

    assert len(client.runs) == 1


def test_two_daemons_are_two_answers(tmp_path):
    """The cache is keyed by the daemon, because that is what the answer is about.

    One shell talking to a remote 'DOCKER_HOST' and one talking to the machine's
    own daemon are two different answers, and a cache that held one would give
    it to the other.
    """
    here, there = _ProbeClient(sees=True), _ProbeClient(sees=False, base_url="tcp://elsewhere:2375")

    assert runtime_python_docker.mounts_are_shared(here, "some/image:tag") is True
    assert runtime_python_docker.mounts_are_shared(there, "some/image:tag") is False


def test_an_image_the_daemon_cannot_bind_for_is_not_available(tmp_path, monkeypatch):
    """Which is what keeps PartCAD from *choosing* this sandbox there.

    'image_available' is the question the context asks before it decides, so a
    machine that would fail on every part answers "no" here and gets conda or a
    virtual environment instead -- rather than a container per part, each one
    failing on a path.
    """
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: _ProbeClient(sees=False))

    assert runtime_python_docker.image_available("some/image:tag", "3.11") is False


def test_an_image_whose_daemon_is_here_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: _ProbeClient(sees=True))

    assert runtime_python_docker.image_available("some/image:tag", "3.11") is True


def test_a_declared_docker_sandbox_says_why_it_cannot_run(tmp_path, monkeypatch):
    """A stated 'pythonSandbox: docker' is obeyed, so it reaches '_start'.

    What it used to reach was 'containers.run' succeeding, and then '-m venv'
    failing with "Permission denied" on a directory the user can write to
    perfectly well -- which names neither the daemon nor the mount. The sandbox
    is unavailable, and the sentence says which knob moves it.
    """
    made = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: _ProbeClient(sees=False))

    with pytest.raises(runtime.SandboxUnavailable, match="cannot see this machine's files|pythonSandbox"):
        made._start()


def test_nothing_is_created_when_the_daemon_is_somewhere_else(tmp_path, monkeypatch):
    """Asked before the container, not after: half a sandbox is worse than none.

    A container started against directories that are not these ones is one the
    next run finds and reuses.
    """
    client = _ProbeClient(sees=False)
    made = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)

    with pytest.raises(runtime.SandboxUnavailable):
        made._start()

    # The probe's own container, and nothing else.
    assert [kwargs.get("name") for _image, kwargs in client.runs] == [None]


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


def _elsewhere(name="somewhere-else") -> str:
    """An absolute directory this context did not ask for, spelled for this host.

    A literal '/somewhere/else' is not one on Windows: it has no drive letter,
    so 'translate' refuses it outright rather than mapping it, and the stub
    below could not even be constructed there. The mount PartCAD is being told
    about is a *host* path, so it has to look like one here.
    """
    return os.path.join(os.path.abspath(os.sep), name)


class _Container:
    """A container that was started with some set of mounts.

    'sources' is either the paths, all writable, or a mapping of path to
    whether it is writable. 'Type' is what tells a bind mount from a volume an
    image declared itself, which PartCAD never asked for and does not compare.

    Each mount lands where 'translate' says, which is what a container PartCAD
    started would carry. A test that wants one landing somewhere else edits
    'attrs' afterwards.
    """

    def __init__(self, sources, status="running"):
        if not isinstance(sources, dict):
            sources = {source: True for source in sources}
        self.attrs = {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": source,
                    # The platform's own mapping, not a hardcoded POSIX one.
                    # Pinning 'windows=False' made this stub disagree with
                    # '_start' on Windows -- its 'Destination' stayed 'C:\\...'
                    # while the real one is '/c/...' -- so every container
                    # looked wrong and the reuse tests failed there and only
                    # there.
                    "Destination": docker_mount.translate(source),
                    "RW": rw,
                }
                for source, rw in sources.items()
            ]
        }
        self.status = status
        self.removed = False
        self.started = False

    def start(self):
        self.started = True

    def remove(self, force=False):
        self.removed = True


class _Client:
    """A daemon on this filesystem, holding at most one sandbox container.

    Two kinds of run reach it. The named one is the sandbox's own container;
    the unnamed one is the mount probe, which every '_start' now makes first,
    and which this stub answers the way a daemon that shares this filesystem
    does. Keeping them apart here rather than in each test is what stops the
    probe from counting as "a container was created".
    """

    def __init__(self, existing=None):
        self.existing = existing
        self.made = None
        self.probes = []
        self.api = types.SimpleNamespace(base_url="http+docker://localhost")
        self.images = types.SimpleNamespace(get=lambda name: name, pull=lambda name: name)
        self.containers = types.SimpleNamespace(get=self._get, run=self._run)

    def _get(self, name):
        import docker

        if self.existing is None:
            raise docker.errors.NotFound(name)
        return self.existing

    def _run(self, image, **kwargs):
        if kwargs.get("name") is None:
            self.probes.append(kwargs)
            return b""
        self.made = kwargs
        # What is created answers to the name afterwards, the way Docker's does,
        # and carries the modes it was asked for. A stub that kept returning the
        # removed one, or that made everything writable, would have the second
        # caller replace a container that is in fact the one it wanted.
        self.existing = _Container({host: spec["mode"] != "ro" for host, spec in (kwargs.get("volumes") or {}).items()})
        return self.existing


def _except_the_probe(client, replacement):
    """Replace 'containers.run' for the *sandbox* container only.

    The mount probe keeps the stub's own answer. A test about a name taken
    between the look-up and the create, or about a refusal that is not a race,
    is not a test about whether the daemon shares this filesystem -- and saying
    so in each of them would be three copies of one fact.
    """
    original = client._run

    def run(image, **kwargs):
        if kwargs.get("name") is None:
            return original(image, **kwargs)
        return replacement(image, **kwargs)

    client.containers.run = run


def _started(tmp_path, monkeypatch, existing):
    made = _runtime(tmp_path)
    client = _Client(existing)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)
    return made, client, made._start()


def _wanted_binds(made):
    mounts = docker_mount.mounts(made._mounted)
    return {host: spec["mode"] != "ro" for host, spec in mounts.items()}


def test_a_container_that_can_see_this_context_is_reused(tmp_path, monkeypatch):
    made = _runtime(tmp_path)
    existing = _Container(_wanted_binds(made), status="exited")

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
    existing = _Container([_elsewhere()])

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is not existing
    assert existing.removed is True
    assert client.made is not None


def test_a_container_holding_more_than_was_asked_for_is_replaced(tmp_path, monkeypatch):
    """It used to be reused, and that leaked one context's directory into another.

    The check was for coverage: a container with *more* mounts than the request
    satisfied it. Nearly harmless while the set was the state directory and the
    context root; not once a context can name a directory of the user's own, as
    an ad-hoc conversion does -- the container it started still has that
    directory mounted, and the next context wanting this image would have
    inherited it without ever asking.
    """
    binds = _wanted_binds(_runtime(tmp_path))
    binds[str(tmp_path / "somebody-elses-files")] = True
    existing = _Container(binds)

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is not existing
    assert existing.removed is True
    assert client.made is not None


def test_a_container_mounting_it_somewhere_else_is_replaced(tmp_path, monkeypatch):
    """The right directories in the wrong places is still the wrong container.

    A destination is derived from its source, so the two agree for as long as
    that derivation does. The run where it does not is a PartCAD that changed
    it, whose containers from before the change are still on the machine -- and
    a path the host and the container disagree about is the whole class of bug
    binding directories onto themselves exists to prevent.
    """
    made = _runtime(tmp_path)
    existing = _Container(_wanted_binds(made))
    existing.attrs["Mounts"][0]["Destination"] = "/somewhere/else"

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is not existing
    assert existing.removed is True


def test_a_volume_the_image_declared_is_not_compared(tmp_path, monkeypatch):
    """PartCAD never asked for it and cannot match it.

    Comparing it in would replace such an image's container before every command.
    """
    made = _runtime(tmp_path)
    existing = _Container(_wanted_binds(made))
    existing.attrs["Mounts"].append({"Type": "volume", "Source": "some-volume", "RW": True})

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is existing
    assert client.made is None


# --------------------------------------------------------------------------- #
# Two of them starting at once                                                 #
# --------------------------------------------------------------------------- #


class _StaleContainer(_Container):
    """One carrying this name with the wrong mounts, so '_start' replaces it.

    Which is the only path that removes anything, and therefore the only one
    where two callers can collide.
    """

    def __init__(self, removals, error=None, status="running", client=None):
        super().__init__([_elsewhere()], status=status)
        self.removals = removals
        self.error = error
        self.client = client

    def remove(self, force=False):
        self.removals.append(force)
        if self.error is not None:
            raise self.error
        if self.client is not None:
            self.client.existing = None


def _conflict(message):
    """What Docker answers with when two callers want one name at one moment."""
    import docker

    response = types.SimpleNamespace(status_code=409, reason="Conflict", url="http+docker://localhost/containers/x")
    return docker.errors.APIError(message, response=response, explanation=message)


def test_two_threads_starting_one_container_remove_it_once(tmp_path, monkeypatch):
    """The 409 that CI caught: two threads both replacing one container.

    PartCAD instantiates parts concurrently, so two sandboxes reach '_start'
    together. Both found the container wrong, both called 'remove(force=True)',
    and Docker answers the second with "removal of container ... is already in
    progress" -- which arrived as a failed render, not as a retry.
    """
    import threading

    removals = []
    client = _Client(None)
    client.existing = _StaleContainer(removals, client=client)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)

    # Two sandboxes, one name: what two part factories in one context are.
    sandboxes = [_runtime(tmp_path) for _ in range(2)]
    assert sandboxes[0].container_name == sandboxes[1].container_name

    # Slow enough that both threads are inside the look-up together when
    # nothing serializes them -- which is the interleaving that happened in CI
    # and which a test running them back to back would never produce.
    inner = client.containers.get

    def _slow_get(name):
        found = inner(name)
        time.sleep(0.05)
        return found

    client.containers.get = _slow_get

    started = threading.Barrier(len(sandboxes))
    errors = []

    def start(sandbox):
        started.wait()
        try:
            sandbox._start()
        except Exception as e:  # noqa: BLE001 - the point is that there are none
            errors.append(e)

    threads = [threading.Thread(target=start, args=(s,)) for s in sandboxes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # The second caller finds the container the first one made, under the name
    # it looked up, and it is the one it wanted -- so it never reaches the
    # removal at all. Unserialized, both find the stale one and both remove it,
    # and Docker answers the second with a 409.
    assert len(removals) == 1


def test_a_removal_already_in_progress_is_waited_out(tmp_path, monkeypatch):
    """Another *process* removing it is not something a lock here can prevent.

    It is also not a failure: gone is what this wanted. The attempt gives up
    its turn rather than trying to create the replacement while the name is
    still taken.
    """
    monkeypatch.setattr(runtime_python_docker, "_START_RETRY_DELAY", 0)
    made = _runtime(tmp_path)
    existing = _StaleContainer([], error=_conflict("removal of container abc is already in progress"))
    client = _Client(existing)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)

    # It goes: the second turn finds nothing under the name and creates one.
    client.existing = existing

    def _get(name):
        import docker

        if client.existing is None:
            raise docker.errors.NotFound(name)
        found, client.existing = client.existing, None
        return found

    client.containers.get = _get

    got = made._start()

    assert got is not None
    assert client.made is not None


def test_a_name_taken_between_the_lookup_and_the_create_is_retried(tmp_path, monkeypatch):
    """Another process created it first, and it is named after these mounts.

    So it is very likely exactly the container this one was about to make --
    which is what going round and inspecting it establishes.
    """
    monkeypatch.setattr(runtime_python_docker, "_START_RETRY_DELAY", 0)
    made = _runtime(tmp_path)
    client = _Client(None)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)

    theirs = _Container(_wanted_binds(made))

    def _run(image, **kwargs):
        client.existing = theirs
        raise _conflict('Conflict. The container name "%s" is already in use' % kwargs["name"])

    _except_the_probe(client, _run)

    got = made._start()

    assert got is theirs


def test_a_refusal_that_is_not_a_race_is_raised(tmp_path, monkeypatch):
    """A sandbox that cannot start is a thing to report, not to retry."""
    import docker

    monkeypatch.setattr(runtime_python_docker, "_START_RETRY_DELAY", 0)
    made = _runtime(tmp_path)
    client = _Client(None)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)

    response = types.SimpleNamespace(
        status_code=500, reason="Server Error", url="http+docker://localhost/containers/create"
    )

    def _run(image, **kwargs):
        raise docker.errors.APIError(
            "no space left on device", response=response, explanation="no space left on device"
        )

    _except_the_probe(client, _run)

    with pytest.raises(docker.errors.APIError, match="no space left"):
        made._start()


def test_the_temporary_directory_is_mounted(tmp_path):
    """Because plenty of things land there without asking to be mounted.

    An ad-hoc command's generated package, a factory's intermediate, a
    caller's own 'mkstemp' -- each one a container could not open was the same
    bug found somewhere new, and each was fixed by moving the file. One fixed
    mount ends the category instead.
    """
    made = _runtime(tmp_path)

    assert tempfile.gettempdir() in made._mounted


def test_two_ad_hoc_runs_ask_for_the_same_mounts(tmp_path, monkeypatch):
    """Which is what keeps the warm container, and what a temp path would lose.

    An ad-hoc command's context root is a fresh 'mkdtemp' every time. Unmounted,
    each run named a directory no previous run had -- a mount set that differs
    is a container that gets replaced, so 'pc convert' threw the container away
    and started another every single time. Two runs, one mount set.
    """
    _one_big_directory(tmp_path, monkeypatch)
    os.makedirs(tmp_path / "tmp", exist_ok=True)

    def one_run():
        made = _runtime(tmp_path)
        made.ctx.root_path = tempfile.mkdtemp(dir=str(tmp_path / "tmp"))
        return sorted(docker_mount.mounts(made._mounted)), made.container_name

    first, first_name = one_run()
    second, second_name = one_run()

    assert first == second, (first, second)
    assert first_name == second_name


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
    try:
        os.symlink(str(tmp_path / "only-inside-the-image" / "python3"), made._host_venv_python)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
        pytest.skip("this platform will not create a symlink here")

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
    """A docker client that holds some images and can be asked to pull others.

    On this machine's filesystem, so the mount probe 'image_available' makes
    passes: what these tests are about is which names are tried and in what
    order, and a daemon somewhere else has its own tests above.
    """

    def __init__(self, local=(), pullable=()):
        self.local = set(local)
        self.pullable = set(pullable)
        self.pulled = []
        self.api = types.SimpleNamespace(base_url="http+docker://localhost/%d" % id(self))
        self.containers = types.SimpleNamespace(run=lambda image, **kwargs: b"")

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
