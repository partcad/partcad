#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The `docker` sandbox, actually run.

Everything else about this sandbox is tested without a container, because what
is worth pinning about it -- the identity, the command line, the Windows
mapping -- can be decided without one. This is the part that cannot: whether the
design *works*. It mounts the state directory, creates a virtual environment
inside the container at a path the host also knows, installs into it and imports
what it installed.

That sequence is the whole claim the `docker` sandbox makes, and every step of
it is an assumption until something runs it: that the mount lands where it is
supposed to, that a venv built by the image's interpreter is one the host can
see, that pip writes into the mount rather than into the container's own
filesystem, and that the environment survives the container being replaced.

Skipped where there is no container runtime, which is most machines and most of
CI. It needs an image to run in, named by PC_TEST_SANDBOX_IMAGE -- CI builds the
base image in the same run and passes it here; a contributor can point it at a
local build. Deliberately not defaulted to a published tag: a test that silently
pulls a gigabyte from a registry is a test people learn to skip.

One sandbox serves the whole file, and that is not tidiness. Provisioning a
sandbox installs PartCAD's CAD stack into it -- OCP is most of a gigabyte --
so a sandbox per test is that download per test, and the disk to hold five
copies of it. What is under test is the same sandbox at each step anyway.
"""

import os
import shutil
import types

import pytest

from partcad import runtime, runtime_python_docker, wrapper

IMAGE = os.environ.get("PC_TEST_SANDBOX_IMAGE")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not IMAGE, reason="PC_TEST_SANDBOX_IMAGE names no image to run the sandbox in"),
    pytest.mark.skipif(shutil.which("docker") is None, reason="no docker command on this machine"),
]


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """A sandbox on this machine, and the container it started, removed after.

    One for the module: see the note at the top. A test that wants the
    container gone asks for that itself.
    """
    if not runtime.docker_available():
        pytest.skip("no container runtime is answering here")

    root = tmp_path_factory.mktemp("sandbox")
    ctx = types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(root / "state")),
        root_path=str(root / "pkg"),
    )
    os.makedirs(ctx.root_path, exist_ok=True)

    sandbox = runtime_python_docker.DockerPythonRuntime(ctx, "3.11", image=IMAGE)
    try:
        yield sandbox
    finally:
        import docker

        try:
            docker.from_env().containers.get(sandbox.container_name).remove(force=True)
        except Exception:
            pass


def test_a_command_runs_in_the_container(made):
    """The first thing, and the one everything else is built on."""
    exitcode, stdout, stderr = made.run(["-c", "import sys; print(sys.executable)"])
    assert exitcode == 0, stderr
    # The interpreter that answered is the container's, not this machine's.
    assert stdout.strip().startswith("/"), stdout
    assert not stdout.strip().startswith(os.path.dirname(os.__file__)), stdout


def test_a_wrapper_is_handed_its_request_and_answers(made):
    """The shape every part factory uses: a request on stdin, an answer on stdout.

    'session=' is part of that shape, and a sandbox that did not take it refused
    the call before a container was involved -- so this checks the call as it is
    made, not only that something runs.
    """
    exitcode, stdout, stderr = made.run(
        ["-c", "import sys; print(sys.stdin.read().upper())"], "a request", session=None
    )
    assert exitcode == 0, stderr
    assert "A REQUEST" in stdout


def test_a_wrapper_file_can_be_opened_by_the_interpreter_over_there(made):
    """PartCAD's own installation is a mount too, and this is why.

    Every wrapper is run by path, and that path is in neither of the other two
    mounts unless the installation happens to be inside one -- which a checkout
    with an in-project virtual environment is and the frozen bundle is not. So
    the bundle rendered nothing through this sandbox: "can't open file
    '.../_internal/partcad/wrappers/wrapper_plugin.py'". The fixture's state
    directory and context root are both under a temporary directory, so the
    installation here is outside both, exactly as it is in a bundle.

    Read rather than executed: a wrapper expects a request on stdin and the CAD
    stack around it, and neither is what is in question. Whether the container
    can see the file is.
    """
    path = wrapper.get("plugin.py")
    exitcode, stdout, stderr = made.run(["-c", "import sys; print(open(sys.argv[1]).readline())", path])

    assert exitcode == 0, stderr
    assert stdout.strip(), stdout


def test_the_environment_is_created_where_the_host_can_see_it(made):
    """The mount claim, checked from the outside.

    The container creates the virtual environment; the host is asked whether it
    is there. If the mount is wrong, or the paths differ, or pip wrote into the
    container's own filesystem, this is where it shows.
    """
    made.once()
    # 'lexists', because 'bin/python' is a symlink to the *image's* interpreter
    # and the host has no file at that path -- which is the arrangement, not a
    # fault: the environment is the host's to see and the interpreter is the
    # container's to run.
    assert os.path.lexists(made._host_venv_python), os.listdir(os.path.dirname(made.path))


def test_a_package_installed_over_there_imports_over_there(made):
    """pip into a mounted environment, and an import out of it.

    'six' because it is small, pure Python, and has no dependencies -- what is
    under test is the sandbox, not the packaging of anything in particular.
    """
    import asyncio

    asyncio.run(made.ensure_async("six"))
    exitcode, stdout, stderr = made.run(["-c", "import six; print(six.__version__)"])
    assert exitcode == 0, stderr
    assert stdout.strip(), "six imported but reported no version"


def test_the_environment_outlives_the_container(made):
    """Which is what mounting buys over copying.

    A container is cattle -- it is removed by `pc system prune`, by a reboot, by
    a `docker rm` somebody typed. What a package installed must not go with it.

    It takes the container away from the sandbox the rest of the file shares,
    which is fine and is the point: the next command starts another one.
    """
    import asyncio

    import docker

    asyncio.run(made.ensure_async("six"))

    docker.from_env().containers.get(made.container_name).remove(force=True)
    made._container = None

    exitcode, stdout, stderr = made.run(["-c", "import six; print('still here')"])
    assert exitcode == 0, stderr
    assert "still here" in stdout


def test_what_the_sandbox_writes_is_readable_afterwards(made):
    """Files come back owned by whoever ran PartCAD, not by the image's user.

    On Linux a bind mount passes uids straight through, so a container running
    as its own user leaves files the person who started it cannot open. That is
    why the runtime passes the host's uid; this is the check that it took.
    """
    written = os.path.join(made.ctx.root_path, "written-by-the-sandbox.txt")
    exitcode, _, stderr = made.run(["-c", "open(%r, 'w').write('hello')" % written])
    assert exitcode == 0, stderr
    with open(written) as f:
        assert f.read() == "hello"
