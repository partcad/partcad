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

Nothing here installs a CAD stack. What is under test is the sandbox, and a
sandbox that can install and import a pure-Python package is one that can
install and import OCP -- only slower.
"""

import os
import shutil
import types

import pytest

from partcad import runtime, runtime_python_docker


IMAGE = os.environ.get("PC_TEST_SANDBOX_IMAGE")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not IMAGE, reason="PC_TEST_SANDBOX_IMAGE names no image to run the sandbox in"),
    pytest.mark.skipif(shutil.which("docker") is None, reason="no docker command on this machine"),
]


@pytest.fixture
def made(tmp_path):
    """A sandbox on this machine, and the container it started, removed after."""
    if not runtime.docker_available():
        pytest.skip("no container runtime is answering here")

    ctx = types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state")),
        root_path=str(tmp_path / "pkg"),
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


def test_the_environment_is_created_where_the_host_can_see_it(made):
    """The mount claim, checked from the outside.

    The container creates the virtual environment; the host is asked whether it
    is there. If the mount is wrong, or the paths differ, or pip wrote into the
    container's own filesystem, this is where it shows.
    """
    made.once()
    assert os.path.isfile(made._host_venv_python), os.listdir(os.path.dirname(made.path))


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
