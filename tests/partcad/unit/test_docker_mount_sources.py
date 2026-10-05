#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'docker' sandbox from inside a container whose Docker daemon is the host's.

The dev container this repository ships binds the host's Docker socket, so the
daemon resolves a bind source against the *host's* filesystem, where the paths
PartCAD sees do not exist. Most of them are mounts of the dev container, though,
and the daemon knows where each of those really is -- so the sandbox binds from
there and keeps the target, and inside the sandbox every path is still the one
PartCAD knows.
"""

import os
import tempfile
import types

import docker
import pytest

from partcad import docker_mount, runtime, runtime_python_docker

# ---- docker_mount ------------------------------------------------------------

SOURCES = [
    ("/workspaces/partcad", "/home/me/partcad"),
    ("/home/vscode/.partcad", "/var/lib/docker/volumes/state/_data"),
    ("/home/vscode/.partcad/cache", "/var/lib/docker/volumes/cache/_data"),
]


def test_a_path_is_backed_by_the_mount_holding_it():
    assert docker_mount.backed_by("/workspaces/partcad/examples", SOURCES) == "/home/me/partcad/examples"
    assert docker_mount.backed_by("/workspaces/partcad", SOURCES) == "/home/me/partcad"


def test_the_innermost_mount_wins():
    assert docker_mount.backed_by("/home/vscode/.partcad/cache/x", SOURCES) == "/var/lib/docker/volumes/cache/_data/x"


def test_a_textual_prefix_is_not_a_parent():
    assert docker_mount.backed_by("/workspaces/partcad-other", SOURCES) is None


def test_binds_come_from_where_the_daemon_has_them_and_land_where_they_are_here():
    mounts = docker_mount.mounts(["/workspaces/partcad/examples", "/home/vscode/.partcad"], sources=SOURCES)
    assert mounts == {
        "/home/me/partcad": {"bind": "/workspaces/partcad", "mode": "rw"},
        "/var/lib/docker/volumes/state/_data": {"bind": "/home/vscode/.partcad", "mode": "rw"},
    }


def test_every_context_asks_for_the_same_mounts():
    """What the home directory does on a host. A container is shared by every context
    using its image and replaced when the mounts differ -- from under the one that
    started it, whose next command then ran without its package."""
    one = docker_mount.mounts(["/workspaces/partcad/examples/a", "/workspaces/partcad/src"], sources=SOURCES)
    two = docker_mount.mounts(["/workspaces/partcad/tests/b", "/workspaces/partcad/src"], sources=SOURCES)
    assert one == two == {"/home/me/partcad": {"bind": "/workspaces/partcad", "mode": "rw"}}


def test_a_directory_the_daemon_does_not_have_is_not_bound():
    """Binding it would have the daemon make an empty one of that name on the host."""
    assert docker_mount.mounts(["/home/vscode"], sources=SOURCES) == {}


def test_a_directory_inside_another_is_still_bound_once():
    mounts = docker_mount.mounts(["/home/vscode/.partcad", "/home/vscode/.partcad/cache/x"], sources=SOURCES)
    # The cache volume is a mount of its own inside the state volume; bound once
    # each, since the outer bind does not carry what is mounted inside it.
    assert mounts == {
        "/var/lib/docker/volumes/state/_data": {"bind": "/home/vscode/.partcad", "mode": "rw"},
        "/var/lib/docker/volumes/cache/_data": {"bind": "/home/vscode/.partcad/cache", "mode": "rw"},
    }


def test_without_sources_nothing_changes():
    assert docker_mount.mounts(["/srv/pkg"], windows=False) == {"/srv/pkg": {"bind": "/srv/pkg", "mode": "rw"}}


# ---- finding them ------------------------------------------------------------

DAEMON_TMP = "/var/lib/docker/volumes/tmp/_data"


class _HostDaemon:
    """The host's daemon, seen from a dev container that has '/tmp' on a volume.

    It finds the probe's file only when the bind's source is where it keeps that
    volume -- which is the whole difference between binding a path and binding
    the directory that path is here.
    """

    def __init__(self, me="devcontainer", mounts=None):
        self.me = me
        self.own_mounts = (
            mounts
            if mounts is not None
            else [
                {"Type": "volume", "Source": DAEMON_TMP, "Destination": tempfile.gettempdir()},
                {"Type": "tmpfs", "Destination": "/run"},
            ]
        )
        self.runs = []
        self.api = types.SimpleNamespace(base_url="unix://var/run/docker.sock")
        self.containers = types.SimpleNamespace(get=self._get, run=self._run)

    def _get(self, name):
        if name == self.me:
            return types.SimpleNamespace(attrs={"Mounts": self.own_mounts})
        raise docker.errors.NotFound(name)

    def _run(self, image, **kwargs):
        self.runs.append(kwargs["volumes"])
        if any(source.startswith(DAEMON_TMP) for source in kwargs["volumes"]):
            return b""
        raise docker.errors.ContainerError(
            container="probe", exit_status=1, command=kwargs.get("command"), image=image, stderr=b""
        )


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    runtime_python_docker._MOUNTS_SHARED.clear()
    monkeypatch.delenv("PC_DOCKER_MOUNT_SOURCES", raising=False)
    monkeypatch.setattr(runtime_python_docker.socket, "gethostname", lambda: "devcontainer")
    yield
    runtime_python_docker._MOUNTS_SHARED.clear()


def test_inside_a_container_of_that_daemon_its_mounts_are_the_answer():
    daemon = _HostDaemon()
    sources = runtime_python_docker.mount_sources(daemon, "img")
    assert sources == [(tempfile.gettempdir(), DAEMON_TMP)]
    assert runtime_python_docker.mounts_are_shared(daemon, "img") is True
    # Asked plainly first, then with the mapping -- and the second time the
    # probe's directory was bound from where the daemon keeps it.
    assert len(daemon.runs) == 2
    assert all(source.startswith(DAEMON_TMP) for source in daemon.runs[1])


def test_a_daemon_this_process_is_not_a_container_of_has_no_answer():
    """'DOCKER_HOST' on another machine: nothing there knows where these files are."""
    daemon = _HostDaemon(me="somebody-else")
    assert runtime_python_docker.mount_sources(daemon, "img") is False


def test_mounts_that_do_not_hold_the_probe_are_no_answer():
    daemon = _HostDaemon(mounts=[{"Type": "bind", "Source": "/home/me/x", "Destination": "/workspaces/x"}])
    assert runtime_python_docker.mount_sources(daemon, "img") is False


def test_they_can_be_named_by_hand(monkeypatch):
    monkeypatch.setenv("PC_DOCKER_MOUNT_SOURCES", "%s=%s; =ignored" % (tempfile.gettempdir(), DAEMON_TMP))
    daemon = _HostDaemon(me="somebody-else")
    assert runtime_python_docker.mount_sources(daemon, "img") == [(tempfile.gettempdir(), DAEMON_TMP)]


# ---- the sandbox's own mounts --------------------------------------------------


def _sandbox(tmp_path):
    ctx = types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state")),
        root_path=str(tmp_path / "package"),
        sandbox_paths=(),
    )
    return runtime_python_docker.DockerPythonRuntime(ctx, "3.11", image="ghcr.io/x/solver:abc")


def test_every_directory_but_home_has_to_be_backed(tmp_path):
    sandbox = _sandbox(tmp_path)
    sources = [(str(tmp_path), "/daemon/t"), (tempfile.gettempdir(), DAEMON_TMP)]
    install = runtime_python_docker.INSTALL_DIR
    with pytest.raises(runtime.SandboxUnavailable) as raised:
        sandbox._mounts(sources)
    # Named, so the reader knows what to mount.
    assert install in str(raised.value)
    assert os.path.expanduser("~") not in str(raised.value).replace(install, "")


def test_home_is_left_out_and_the_rest_bound_from_the_daemon(tmp_path):
    sandbox = _sandbox(tmp_path)
    install = runtime_python_docker.INSTALL_DIR
    sources = [
        (str(tmp_path), "/daemon/t"),
        (tempfile.gettempdir(), DAEMON_TMP),
        (install, "/daemon/install"),
    ]
    mounts = sandbox._mounts(sources)
    assert mounts["/daemon/install"] == {"bind": install, "mode": "rw"}
    assert all(spec["bind"] != os.path.expanduser("~") for spec in mounts.values())
    assert sandbox._mount_sources == sources


def test_unbacked_names_what_the_daemon_cannot_bind():
    assert runtime_python_docker.unbacked(["/workspaces/partcad/x", "/opt/y"], SOURCES) == ["/opt/y"]
    # Where the daemon shares this filesystem, nothing is unbacked.
    assert runtime_python_docker.unbacked(["/opt/y"], None) == []


# ---- whose container it is ---------------------------------------------------


def _dev_container(tmp_path, volume, home=None):
    """A sandbox in a dev container whose state and temp dirs come from ``volume``.

    'here' is shared by every simulated dev container, the way '/workspaces/x'
    and '/tmp' are the same paths in two containers built from one config; the
    daemon-side sources are what differ, as each container's volumes do.
    """
    sandbox = _sandbox(tmp_path)
    if home is not None:
        sandbox.ctx.user_config.internal_state_dir = str(home / ".partcad")
    sources = [
        (str(tmp_path), "/var/lib/docker/volumes/%s-work/_data" % volume),
        (tempfile.gettempdir(), "/var/lib/docker/volumes/%s-tmp/_data" % volume),
        (runtime_python_docker.INSTALL_DIR, "/var/lib/docker/volumes/%s-install/_data" % volume),
    ]
    return sandbox, sources


def test_two_dev_containers_on_one_host_are_two_containers(tmp_path):
    """What they had in common was the host's daemon and one container name.

    Named after the image alone, every dev container on a machine shared one
    sandbox container: each replaced it with its own mounts, and the others'
    commands, run by name, ran in that one -- writing where they never looked.
    """
    one, one_sources = _dev_container(tmp_path, "devcontainer-one")
    two, two_sources = _dev_container(tmp_path, "devcontainer-two")
    one._mounts(one_sources)
    two._mounts(two_sources)
    assert one.container_name != two.container_name
    assert one.container_name.startswith(runtime_python_docker.container_name(one.image) + "-")


def test_one_dev_container_is_one_container_whatever_its_home(tmp_path):
    """A test with a temporary '~' and the daemon with the real one used to need
    different mounts -- and so replaced each other's container."""
    os.makedirs(tmp_path / "home-a")
    os.makedirs(tmp_path / "home-b")
    real, sources = _dev_container(tmp_path, "devcontainer-one", home=tmp_path / "home-a")
    temporary, _ = _dev_container(tmp_path, "devcontainer-one", home=tmp_path / "home-b")
    assert real._mounts(sources) == temporary._mounts(sources)
    assert real.container_name == temporary.container_name


def test_on_an_ordinary_host_a_project_elsewhere_gets_its_own_container(tmp_path):
    """Two PartCAD processes on one host, one of them on a package somewhere else.

    The second needs a mount the first does not; it gets a container of its own
    rather than replacing the one the first is running commands in.
    """
    here = _sandbox(tmp_path)
    elsewhere = _sandbox(tmp_path)
    # Outside the home and the temporary directory on every platform, and a
    # path Windows can mount too: a POSIX-only one is not, on the Windows legs.
    elsewhere.ctx.root_path = os.path.join(os.path.abspath(os.sep), "elsewhere", "package")
    here._mounts(None)
    elsewhere._mounts(None)
    assert here.container_name != elsewhere.container_name


def test_only_directories_are_bound(tmp_path):
    """The host's Docker socket is bound into a dev container; a sandbox gets none of it."""
    socket_file = tmp_path / "docker.sock"
    socket_file.write_text("")
    mounts = runtime_python_docker.client_mounts(
        [(str(socket_file), "/var/run/docker.sock"), (str(tmp_path), "/daemon/t")]
    )
    assert mounts == {"/daemon/t": {"bind": str(tmp_path), "mode": "rw"}}


class _HostDockerDaemon:
    """The host's daemon, shared by two dev containers: containers by name, removed for real."""

    def __init__(self):
        self.containers_by_name = {}
        self.removed = []
        self.api = types.SimpleNamespace(base_url="unix://var/run/docker.sock")
        self.images = types.SimpleNamespace(get=lambda name: name, pull=lambda name: name)
        self.containers = types.SimpleNamespace(get=self._get, run=self._run)

    def _get(self, name):
        if name not in self.containers_by_name:
            raise docker.errors.NotFound(name)
        return self.containers_by_name[name]

    def _run(self, image, name=None, volumes=None, **_kwargs):
        daemon = self

        class _Made:
            status = "running"
            attrs = {
                "Mounts": [
                    {"Type": "bind", "Source": source, "Destination": spec["bind"], "RW": True}
                    for source, spec in (volumes or {}).items()
                ]
            }

            def remove(self, force=False):
                daemon.removed.append(name)
                daemon.containers_by_name.pop(name, None)

        made = _Made()
        self.containers_by_name[name] = made
        return made


def test_a_second_dev_container_does_not_remove_the_first_ones_container(tmp_path, monkeypatch):
    """The problem itself, end to end through '_start'."""
    daemon = _HostDockerDaemon()
    one, one_sources = _dev_container(tmp_path, "devcontainer-one")
    two, two_sources = _dev_container(tmp_path, "devcontainer-two")
    sources_of = {id(one): one_sources, id(two): two_sources}
    starting = []

    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker.docker, "from_env", lambda: daemon)
    monkeypatch.setattr(runtime_python_docker, "resolve_image", lambda client, image, version="": image)
    monkeypatch.setattr(runtime_python_docker, "mount_sources", lambda client, image: sources_of[starting[-1]])

    for sandbox in (one, two):
        starting.append(id(sandbox))
        sandbox._start()

    assert daemon.removed == []
    assert set(daemon.containers_by_name) == {one.container_name, two.container_name}
