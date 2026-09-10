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
        sandbox_paths_read_only=[],
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


def test_two_sets_of_mounts_are_two_containers(tmp_path):
    """Because one name shared by two contexts is a name they fight over.

    Each found the other's container mounted wrong and replaced it, and each
    then ran commands in a container that could not see its own package. The
    name carries the mounts so that a container answering to it is the right
    one, rather than one to arbitrate over.
    """
    one = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two.ctx.sandbox_paths = [str(tmp_path / "somebody-elses-files")]

    assert one.container_name != two.container_name
    # Still one sandbox directory: the environment is per image and lives under
    # the state directory, which both of them mount.
    assert one.path == two.path


def test_the_same_mounts_are_the_same_container(tmp_path):
    one = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    two = _runtime(tmp_path, image="ghcr.io/x/solver:abc")
    one.ctx.sandbox_paths = [str(tmp_path / "shared")]
    two.ctx.sandbox_paths = [str(tmp_path / "shared")]

    assert one.container_name == two.container_name


def test_the_name_follows_a_directory_named_after_the_sandbox_was_built(tmp_path):
    """An ad-hoc command names its directories on the context, and that is later.

    So the name cannot be decided in '__init__' -- it would be the name of a
    container mounting neither the input nor the output.
    """
    made = _runtime(tmp_path)
    before = made.container_name
    made.ctx.sandbox_paths = [str(tmp_path / "output")]

    assert made.container_name != before


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
    return any(docker_mount.contains(mount, path, windows=False) for mount in docker_mount.mounts(made._mounted))


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


def test_a_context_that_names_none_mounts_the_usual_three(tmp_path):
    """Which is every context but an ad-hoc one."""
    made = _runtime(tmp_path)

    assert sorted(made._mounted) == sorted(
        [
            made.ctx.user_config.internal_state_dir,
            runtime_python_docker.INSTALL_DIR,
            made.ctx.root_path,
        ]
    )


def test_the_installation_is_mounted_read_only(tmp_path):
    """What is sandboxed must not be able to edit what sandboxes it."""
    made = _runtime(tmp_path)
    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)
    assert mounts[runtime_python_docker.INSTALL_DIR]["mode"] == "ro"
    assert mounts[made.ctx.user_config.internal_state_dir]["mode"] == "rw"
    assert mounts[made.ctx.root_path]["mode"] == "rw"


def test_a_wrapper_path_is_rewritten_on_a_windows_host(tmp_path, monkeypatch):
    """Which the installation being one of the mounts is what makes possible.

    'rewrite' only knows the mounts it is handed, so on Windows an installation
    that is not one of them is not merely unreachable -- it is handed to the
    container spelled 'C:\\...', which is not a path over there at all.
    """
    install = "C:\\Program Files\\PartCAD\\_internal\\partcad"
    monkeypatch.setattr(runtime_python_docker, "INSTALL_DIR", install)
    made = _runtime(tmp_path)

    # What '_exec' does to every argument, with 'windows' stated rather than
    # taken from 'os.name': patching that globally is what the two tests below
    # have to do, and it leaves pytest formatting a Linux path the Windows way
    # if anything in the test fails.
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
        "HOME=" + made._container_home,
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

    assert home == "HOME=" + made._container_home
    # Under the state directory, which is mounted, writable, and outlives the
    # container -- a cache written there is one the next run still has.
    assert made._container_home.startswith(made.ctx.user_config.internal_state_dir)


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
                    "Destination": docker_mount.translate(source, windows=False),
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
        # What is created answers to the name afterwards, the way Docker's does,
        # and carries the modes it was asked for. A stub that kept returning the
        # removed one, or that made everything writable, would have the second
        # caller replace a container that is in fact the one it wanted.
        self.existing = _Container({host: spec["mode"] != "ro" for host, spec in (kwargs.get("volumes") or {}).items()})
        return self.existing


def _started(tmp_path, monkeypatch, existing):
    made = _runtime(tmp_path)
    client = _Client(existing)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr("docker.from_env", lambda: client)
    return made, client, made._start()


def _wanted_binds(made):
    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)
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
    existing = _Container(["/somewhere/else"])

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


def test_a_container_that_mounts_it_writable_is_replaced(tmp_path, monkeypatch):
    """The mode is half of the contract.

    A directory one context was allowed to write is not one a later context
    that asked for it read-only may write.
    """
    made = _runtime(tmp_path)
    binds = dict(_wanted_binds(made))
    binds[runtime_python_docker.INSTALL_DIR] = True
    existing = _Container(binds)

    _made, client, got = _started(tmp_path, monkeypatch, existing)

    assert got is not existing
    assert existing.removed is True


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
        super().__init__(["/somewhere/else"], status=status)
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

    client.containers.run = _run

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

    client.containers.run = _run

    with pytest.raises(docker.errors.APIError, match="no space left"):
        made._start()


# --------------------------------------------------------------------------- #
# What may be written                                                          #
# --------------------------------------------------------------------------- #


def test_a_path_the_context_only_reads_is_mounted_read_only(tmp_path):
    """An ad-hoc conversion's input is the user's own file, and it is only read."""
    made = _runtime(tmp_path)
    made.ctx.sandbox_paths_read_only = [str(tmp_path / "inputs")]

    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)

    # Visible -- it is the file being converted -- and not writable.
    assert mounts[str(tmp_path / "inputs")]["mode"] == "ro"


def test_a_path_that_is_also_written_stays_writable(tmp_path):
    """Converting a file into the directory it came from is an ordinary thing to do.

    The demand for write access is the specific claim, so it wins over the
    input's "I only read this".
    """
    made = _runtime(tmp_path)
    both = str(tmp_path / "models")
    made.ctx.sandbox_paths = [both]
    made.ctx.sandbox_paths_read_only = [both]

    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)

    assert mounts[both]["mode"] == "rw"


def test_a_writable_path_under_a_read_only_one_keeps_the_whole_mount_writable(tmp_path):
    """'pc convert thing.step -o out/thing.stl', which used to be unable to write.

    The output directory is inside the input's, so 'mounts' keeps only the
    outer one -- and marking that read-only leaves the export with nowhere to
    land. Write access wins over the subtree it was asked for, the same way it
    wins when the two directories are one: a mount that cannot be written is
    not a weaker version of what was requested, it is a failure.
    """
    made = _runtime(tmp_path)
    inputs = str(tmp_path / "models")
    made.ctx.sandbox_paths = [os.path.join(inputs, "out")]
    made.ctx.sandbox_paths_read_only = [inputs]

    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)

    assert mounts[inputs]["mode"] == "rw"
    # And it is the only mount covering the output, which is the reason.
    assert os.path.join(inputs, "out") not in mounts


def test_a_read_only_path_beside_a_writable_one_stays_read_only(tmp_path):
    """Neither contains the other, so the claim about one says nothing about it."""
    made = _runtime(tmp_path)
    made.ctx.sandbox_paths = [str(tmp_path / "out")]
    made.ctx.sandbox_paths_read_only = [str(tmp_path / "inputs")]

    mounts = docker_mount.mounts(made._mounted, read_only=made._mounted_read_only)

    assert mounts[str(tmp_path / "inputs")]["mode"] == "ro"
    assert mounts[str(tmp_path / "out")]["mode"] == "rw"


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
