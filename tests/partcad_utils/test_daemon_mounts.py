#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the mount probe found out, told apart from the probe not running at all.

'mount_sources' starts one container that looks for a file made here, and its
answer decides whether a container can be given this machine's directories. A
container that ran and did not find the file is that answer: the daemon has
the directories somewhere else. One that did not run at all has answered
nothing - and was reported the same way, so an image with no build for this
machine's platform read as "the Docker daemon cannot see this machine's files
... 'DOCKER_HOST' on another machine", which sent its reader to the daemon for
a problem that was in the image. Seen in CI: an amd64-only image on an arm64
runner.
"""

import logging
import types

import docker
import pytest

from partcad_utils import daemon_mounts

AMD64_ONLY = "ghcr.io/example/simulator:latest"
EVERYWHERE = "ghcr.io/example/sandbox:1"
NO_PYTHON = "ghcr.io/example/scratch:1"


class _Image:
    def __init__(self, os_name, architecture):
        self.attrs = {"Os": os_name, "Architecture": architecture}


class _Daemon:
    """As much of a Docker daemon as the probe talks to, on an arm64 machine.

    'sees' says whether a container finds a file the probe made - whether the
    daemon shares this filesystem. An image runs only where it has a build for
    the daemon's platform, and only the interpreters it carries: 'python3' in
    each, except 'NO_PYTHON', which has none. 'refuses_mounts' is a daemon that
    will not make any bind.
    """

    def __init__(self, sees=True, refuses_mounts=False, architecture="aarch64", base_url="unix://var/run/docker.sock"):
        self.sees = sees
        self.refuses_mounts = refuses_mounts
        self.architecture = architecture
        self.runs = []
        self.api = types.SimpleNamespace(base_url=base_url)
        self.built = {
            AMD64_ONLY: _Image("linux", "amd64"),
            EVERYWHERE: _Image("linux", {"aarch64": "arm64", "x86_64": "amd64"}[architecture]),
            NO_PYTHON: _Image("linux", {"aarch64": "arm64", "x86_64": "amd64"}[architecture]),
        }
        self.interpreters = {AMD64_ONLY: {"python3"}, EVERYWHERE: {"python3"}, NO_PYTHON: set()}
        self.images = types.SimpleNamespace(get=self._image)
        self.containers = types.SimpleNamespace(get=self._container, run=self._run)

    def info(self):
        return {"OSType": "linux", "Architecture": self.architecture}

    def _image(self, name):
        if name not in self.built:
            raise docker.errors.ImageNotFound(name)
        return self.built[name]

    def _container(self, name):
        raise docker.errors.NotFound(name)

    def _run(self, image, command=None, volumes=None, **kwargs):
        self.runs.append((image, volumes))
        own = {"aarch64": "arm64", "x86_64": "amd64"}[self.architecture]
        if self.built[image].attrs["Architecture"] != own:
            # What a container with another platform's binary exits with.
            raise docker.errors.ContainerError(
                container="probe",
                exit_status=1,
                command=command,
                image=image,
                stderr=b"exec /usr/bin/python3: exec format error",
            )
        if command[0] not in self.interpreters[image]:
            raise docker.errors.APIError(
                'failed to create task for container: exec: "%s": executable file not found in $PATH' % command[0]
            )
        if volumes and self.refuses_mounts:
            raise docker.errors.APIError("Mounts denied: the path is not shared from the host")
        if volumes and not self.sees:
            raise docker.errors.ContainerError(
                container="probe",
                exit_status=daemon_mounts._PROBE_ABSENT,
                command=command,
                image=image,
                stderr=b"",
            )
        return b""


@pytest.fixture(autouse=True)
def _forget(monkeypatch):
    """The probe's answers are kept for the process, which two tests must not share."""
    monkeypatch.delenv("PC_DOCKER_MOUNT_SOURCES", raising=False)
    daemon_mounts._MOUNTS_SHARED.clear()
    yield
    daemon_mounts._MOUNTS_SHARED.clear()


#
# The probe
#


def test_an_image_with_no_build_for_this_platform_says_so():
    """Not "the daemon cannot see this machine's files": nothing was learnt about the files at all."""
    daemon = _Daemon()

    with pytest.raises(daemon_mounts.ImageDoesNotRun) as raised:
        daemon_mounts.mount_sources(daemon, AMD64_ONLY)

    assert raised.value.reason == "it has no build for linux/arm64 (it is linux/amd64 only)"
    assert raised.value.image == AMD64_ONLY


def test_the_platforms_are_compared_in_one_spelling():
    """The daemon says what the kernel calls the machine, an image what Go does."""
    assert daemon_mounts._platform("linux", "x86_64") == daemon_mounts._platform("linux", "amd64") == "linux/amd64"
    assert daemon_mounts._platform("Linux", "aarch64") == daemon_mounts._platform("linux", "arm64") == "linux/arm64"
    assert daemon_mounts._platform("linux", None) is None


def test_a_container_that_ran_and_found_nothing_is_the_daemon_s_answer():
    """The one answer that is about where the daemon has things, and it is still 'False'."""
    daemon = _Daemon(sees=False)

    assert daemon_mounts.mount_sources(daemon, EVERYWHERE) is False
    assert daemon_mounts.mounts_are_shared(daemon, EVERYWHERE) is False
    # Asked once, with the file mounted: the answer needs no second container.
    assert [volumes is not None and bool(volumes) for _image, volumes in daemon.runs] == [True]


def test_a_daemon_that_shares_this_filesystem_still_says_so():
    assert daemon_mounts.mount_sources(_Daemon(sees=True), EVERYWHERE) is None


def test_an_image_that_does_not_start_for_another_reason_says_what_stopped_it():
    """Its own error, first line, where it is not the platform."""
    daemon = _Daemon()

    with pytest.raises(daemon_mounts.ImageDoesNotRun) as raised:
        daemon_mounts.mount_sources(daemon, NO_PYTHON)

    assert raised.value.reason.startswith("it does not start here: ")
    assert "executable file not found" in raised.value.reason
    assert "no build for" not in raised.value.reason


def test_a_daemon_that_refuses_the_mount_is_still_one_that_cannot_bind_these_files():
    """The image runs - asked again with nothing mounted - so it was the mount: the answer, not the image."""
    daemon = _Daemon(refuses_mounts=True)

    assert daemon_mounts.mount_sources(daemon, EVERYWHERE) is False
    # The probe, and the one container that tells the two failures apart.
    assert [bool(volumes) for _image, volumes in daemon.runs] == [True, False]


#
# What is remembered
#


def test_an_image_that_does_not_run_is_remembered_for_that_image_alone():
    """A wrong platform is the image's: another image on the same daemon gets the daemon's answer."""
    daemon = _Daemon(sees=True)

    for _ in range(2):
        with pytest.raises(daemon_mounts.ImageDoesNotRun):
            daemon_mounts.mount_sources(daemon, AMD64_ONLY)
    # Asked once, for all that it was asked twice: the probe and the check after it.
    assert len(daemon.runs) == 2

    assert daemon_mounts.mount_sources(daemon, EVERYWHERE) is None
    assert daemon_mounts.mounts_are_shared(daemon, EVERYWHERE) is True


def test_an_interpreter_the_image_does_not_have_is_not_an_answer_for_one_it_does():
    """'pc ide open' names an application's interpreter, the sandbox 'python3': each is asked about.

    Remembered under the image alone, the first one's "does not run here" was
    handed to the second without a probe of its own - for an image that runs it.
    """
    daemon = _Daemon(sees=True)

    with pytest.raises(daemon_mounts.ImageDoesNotRun) as raised:
        daemon_mounts.mount_sources(daemon, EVERYWHERE, "python3.13")
    assert '"python3.13": executable file not found' in raised.value.reason

    assert daemon_mounts.mount_sources(daemon, EVERYWHERE, "python3") is None
    assert daemon_mounts.mounts_are_shared(daemon, EVERYWHERE, "python3") is True
    # And each answer is still remembered: asked again, neither starts another container.
    runs = len(daemon.runs)
    with pytest.raises(daemon_mounts.ImageDoesNotRun):
        daemon_mounts.mount_sources(daemon, EVERYWHERE, "python3.13")
    assert daemon_mounts.mount_sources(daemon, EVERYWHERE, "python3") is None
    assert len(daemon.runs) == runs


def test_a_wrong_platform_on_one_daemon_is_not_an_answer_for_another():
    """The same image on an amd64 daemon is an image that runs, and is asked about afresh."""
    here = _Daemon(architecture="aarch64")
    there = _Daemon(architecture="x86_64", base_url="tcp://amd64-builder:2375")

    with pytest.raises(daemon_mounts.ImageDoesNotRun):
        daemon_mounts.mount_sources(here, AMD64_ONLY)
    assert daemon_mounts.mount_sources(there, AMD64_ONLY) is None


#
# What each caller says
#


def test_the_python_sandbox_says_the_image_is_the_reason(monkeypatch):
    """'image_available' is what the fallback to PartCAD's own image reports - see the next test."""
    from partcad import runtime, runtime_python_docker

    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(docker, "from_env", lambda: _Daemon())
    runtime_python_docker._UNAVAILABLE_REASONS.clear()

    assert runtime_python_docker.image_available(AMD64_ONLY, "3.11") is False
    reason = runtime_python_docker.unavailable_reason(AMD64_ONLY)
    assert reason == "it has no build for linux/arm64 (it is linux/amd64 only)"
    assert "DOCKER_HOST" not in reason and "useDockerRemote" not in reason


def test_a_package_s_image_with_no_build_here_falls_back_and_says_why(monkeypatch, tmp_path, caplog):
    """The warning a package's 'dockerImage' gets, and the note its failures repeat.

    It still falls back to PartCAD's own image: 'dockerImage' is where a
    package's parts run best, not the only place they run, and an image this
    machine cannot run is one it cannot get, as an image it cannot pull is.
    """
    import partcad as pc
    from partcad import context as pc_context
    from partcad import runtime, runtime_python_docker

    (tmp_path / "partcad.yaml").write_text("desc: a package\n")
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(docker, "from_env", lambda: _Daemon())
    runtime_python_docker._UNAVAILABLE_REASONS.clear()
    made = []
    monkeypatch.setattr(
        pc_context.runtime_python_all,
        "create",
        lambda ctx, version, sandbox, image=None: made.append((sandbox, image)) or object(),
    )

    ctx = pc.Context(str(tmp_path))
    with caplog.at_level(logging.WARNING):
        ctx.get_python_runtime("3.11", "docker", image=AMD64_ONLY)

    assert made == [("docker", None)]
    note = ctx.docker_image_note(AMD64_ONLY)
    assert "PartCAD's own image was used instead, because it has no build for linux/arm64" in note
    assert "cannot see this machine's files" not in note
    assert "no build for linux/arm64 (it is linux/amd64 only)" in caplog.text


def test_a_declared_docker_sandbox_says_the_image_does_not_run_here(monkeypatch, tmp_path):
    from partcad import runtime, runtime_python_docker

    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(docker, "from_env", lambda: _Daemon())
    sandbox = runtime_python_docker.DockerPythonRuntime.__new__(runtime_python_docker.DockerPythonRuntime)
    sandbox._container = None
    sandbox.image = AMD64_ONLY
    sandbox.version = "3.11"

    with pytest.raises(runtime.SandboxUnavailable) as raised:
        sandbox._start()

    assert "cannot run %s here: it has no build for linux/arm64" % AMD64_ONLY in str(raised.value)
    assert "DOCKER_HOST" not in str(raised.value)


def test_a_container_an_implementation_runs_in_says_its_image_does_not_run_here():
    """KiCad and a plugin's 'container:' bind through 'container_mounts', which says the same."""
    from partcad import container_mounts, runtime

    with pytest.raises(runtime.SandboxUnavailable) as raised:
        container_mounts.bind_mounts(_Daemon(), AMD64_ONLY, ["/tmp"], "KiCad")

    said = str(raised.value)
    assert said.startswith("KiCad runs in a container, and its image %s does not run here: " % AMD64_ONLY)
    assert "it has no build for linux/arm64 (it is linux/amd64 only)" in said
    assert "DOCKER_HOST" not in said


def test_pc_ide_open_says_the_application_s_image_does_not_run_here(monkeypatch):
    from partcad_client import external

    monkeypatch.setattr(docker, "from_env", lambda: _Daemon())

    with pytest.raises(external.ExternalToolError) as raised:
        external._mount_sources(AMD64_ONLY, "python3")

    assert "does not run on this machine: it has no build for linux/arm64 (it is linux/amd64 only)" in str(raised.value)
