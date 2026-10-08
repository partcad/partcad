#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for opening an object in a third-party application (`partcad_client.external`).

Two routes are pinned here, and the rule that decides between them: a locally
installed application is used whenever there is one, and a container is only
ever reached for when the caller has allowed it. Around both, what `open:`
plugins add: an object is opened as it is when its format is on the
application's list and converted when it is not, `pc ide open` waits for the
application to close, and an edit is brought back -- into the source where the
source is a file PartCAD can write, and reported where it is not.

Nothing here runs Docker, and nothing starts an application: `_launch` and
`containers.acquire` are the two places where this module reaches out of the
process, and both are replaced. `test_external_live.py` runs a container.
"""

import os
import re
import sys

import pytest

from partcad_client import external


@pytest.fixture(autouse=True)
def no_local_tools(monkeypatch):
    """A machine with nothing installed on it, unless a test says otherwise.

    `shutil.which` would otherwise answer from whatever the machine running the
    tests happens to have, which is the one thing that decides the whole route.
    """
    monkeypatch.setattr(external.shutil, "which", lambda _name: None)
    monkeypatch.setattr(external.platform, "system", lambda: "Linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("XAUTHORITY", raising=False)


class Launched(list):
    """What would have been started, and what the user does in it before closing it.

    ``edit`` is called with the command, standing in for somebody editing the
    file and closing the application; ``returncode`` is what it exits with.
    """

    edit = None
    returncode = 0


@pytest.fixture
def spawned(monkeypatch):
    """Record what would have been run, instead of running it."""
    started = Launched()

    def launch(args):
        started.append(list(args))
        if started.edit is not None:
            started.edit(list(args))
        return started.returncode

    monkeypatch.setattr(external, "_launch", launch)
    return started


class FakeEndpoint:
    """A container's service: what it was asked to run, and which names it has."""

    def __init__(self, docker, spec):
        self.docker = docker
        self.spec = spec
        self.name = "partcad-%s-test-000000000000" % spec.role

    def which(self, names):
        return {name: ("/usr/bin/" + name if name in self.docker.binaries else None) for name in names}

    def run(
        self,
        command,
        stdin=None,
        cwd=None,
        input_files=None,
        output_files=None,
        input_dirs=None,
        output_dirs=None,
        timeout=None,
        env=None,
    ):
        self.docker.runs.append(
            dict(
                command=list(command),
                cwd=cwd,
                env=dict(env or {}),
                input_files=list(input_files or ()),
                output_files=list(output_files or ()),
                input_dirs=list(input_dirs or ()),
                output_dirs=list(output_dirs or ()),
                timeout=timeout,
            )
        )
        if self.docker.edit is not None:
            self.docker.edit(list(command))
        return self.docker.exit_code, "", self.docker.stderr


class FakeDocker:
    """A container runtime: which containers were asked for, and what ran in them."""

    def __init__(self):
        self.available = True
        self.binaries = ["freecad"]
        self.specs = []
        self.runs = []
        self.edit = None
        self.exit_code = 0
        self.stderr = ""
        self.refuse = None
        # Where the daemon has this machine's directories (see
        # 'external._mount_sources'): None for an ordinary host.
        self.sources = None

    def install(self, monkeypatch):
        from partcad_utils import containers

        monkeypatch.setattr(external, "_docker_available", lambda: self.available)
        monkeypatch.setattr(containers, "acquire", self.acquire)
        monkeypatch.setattr(external, "_mount_sources", lambda reference, python: self.sources)
        return self

    def acquire(self, spec, client=None, ping=None):
        from partcad_utils import containers

        if self.refuse:
            raise containers.ContainerUnavailable(self.refuse)
        self.specs.append(spec)
        return FakeEndpoint(self, spec)

    @property
    def spec(self):
        return self.specs[-1] if self.specs else None

    @property
    def last(self):
        return self.runs[-1] if self.runs else None


@pytest.fixture
def docker(monkeypatch):
    return FakeDocker().install(monkeypatch)


@pytest.fixture
def part(tmp_path):
    """A file inside a workspace, which is what gets opened."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "cube.step"
    path.write_text("ISO-10303-21;\n")
    return path


@pytest.fixture(autouse=True)
def workspace_socket(monkeypatch, tmp_path):
    """Put the workspace's daemon socket where a test can see it get mounted."""
    socket_dir = tmp_path / ".partcad" / "workspaces" / "hash"
    socket_dir.mkdir(parents=True)
    monkeypatch.setattr(external, "socket_path", lambda _root: str(socket_dir / "socket"))
    return socket_dir


# ---------------------------------------------------------------------------
# Choosing between a local installation and a container
# ---------------------------------------------------------------------------


def test_a_local_installation_is_used_when_there_is_one(monkeypatch, spawned, part):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name if name == "freecad" else None)
    result = external.open_file(str(part))
    assert result.method == "native"
    assert spawned == [["/usr/bin/freecad", str(part)]]


def test_a_local_installation_wins_even_when_docker_is_allowed(monkeypatch, spawned, part, docker):
    # `use_docker` is permission to fall back, not a demand for a container.
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name)
    result = external.open_file(str(part), use_docker=True)
    assert result.method == "native"
    assert docker.specs == []


def test_without_docker_allowed_the_failure_says_how_to_allow_it(part):
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part))
    assert "--use-docker" in str(caught.value)
    assert "useDocker" in str(caught.value)


def test_docker_that_does_not_answer_is_not_docker(part, docker):
    docker.available = False
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "Docker" in str(caught.value)


def test_an_unknown_application_lists_the_known_ones(part):
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="solidworks")
    assert "freecad" in str(caught.value)


def test_a_missing_file_is_reported_before_anything_is_started(tmp_path, spawned):
    with pytest.raises(external.ExternalToolError):
        external.open_file(str(tmp_path / "gone.step"))
    assert spawned == []


# ---------------------------------------------------------------------------
# The container
# ---------------------------------------------------------------------------


def _visible(spec, path):
    """Whether ``path`` is inside something the container mounts, at the path it has here."""
    return any(
        external._is_within(str(path), mounted) and value["bind"] == mounted for mounted, value in spec.mounts.items()
    )


def test_the_container_is_created_with_the_workspace_and_the_socket_mounted(part, docker, workspace_socket, tmp_path):
    result = external.open_file(str(part), use_docker=True, mode="mount")
    assert result.method == "docker"
    # Mounted at the path they have on the host, so that one path means the same
    # thing on both sides -- the file argument below is that same host path.
    assert _visible(docker.spec, tmp_path)
    assert _visible(docker.spec, workspace_socket)


def test_the_socket_directory_is_made_so_a_later_daemon_is_visible(part, docker, monkeypatch, tmp_path):
    # The mounts are fixed when the container is created, and this container
    # outlives the daemon several times over: waiting for one to exist would
    # mean a container that can never see the one that eventually starts.
    socket_dir = tmp_path.parent / (tmp_path.name + "-state") / "workspaces" / "hash"
    monkeypatch.setattr(external, "socket_path", lambda _root: str(socket_dir / "socket"))
    external.open_file(str(part), use_docker=True, mode="mount")
    assert socket_dir.is_dir()
    assert _visible(docker.spec, socket_dir)


def test_the_container_is_the_applications_started_the_one_way_every_container_is(part, docker):
    """Not a fixed name any more: `partcad_utils.containers` names it after what it is."""
    external.open_file(str(part), use_docker=True)
    assert docker.spec.role == "open-freecad"
    assert docker.spec.image == external.TOOLS["freecad"].image
    from partcad_utils import containers

    assert containers.container_name(docker.spec).startswith("partcad-open-freecad-latest-")


def test_a_custom_image_replaces_the_default_one(part, docker):
    external.open_file(str(part), use_docker=True, image="freecad/freecad:weekly")
    assert docker.spec.image == "freecad/freecad:weekly"


def test_opening_twice_asks_for_the_same_container(part, docker):
    from partcad_utils import containers

    external.open_file(str(part), use_docker=True)
    external.open_file(str(part), use_docker=True)
    assert containers.identity(docker.specs[0]) == containers.identity(docker.specs[1])


def test_another_workspace_gets_a_container_of_its_own_rather_than_a_refusal(docker, tmp_path, monkeypatch):
    """A container made for one workspace used to be refused for another, with `docker rm -f` as the way out."""
    from partcad_utils import containers

    paths = []
    for name in ("one", "two"):
        workspace = tmp_path / name
        workspace.mkdir()
        (workspace / "partcad.yaml").write_text("name: %s\n" % name)
        (workspace / "cube.step").write_text("ISO-10303-21;\n")
        paths.append(workspace / "cube.step")
    for path in paths:
        # As an editor does: `pc ide open` runs in the window's own workspace.
        monkeypatch.chdir(path.parent)
        external.open_file(str(path), use_docker=True, mode="mount")
    assert containers.identity(docker.specs[0]) != containers.identity(docker.specs[1])


def test_its_home_is_a_volume_so_what_was_configured_outlives_the_container(part, docker):
    external.open_file(str(part), use_docker=True)
    assert docker.spec.volumes == {"partcad-open-freecad-home": {"bind": external.CONTAINER_HOME, "mode": "rw"}}
    assert docker.spec.environment["HOME"] == external.CONTAINER_HOME


def test_in_mount_mode_it_runs_as_this_user_on_linux(part, docker):
    external.open_file(str(part), use_docker=True, mode="mount")
    if hasattr(os, "getuid"):
        assert docker.spec.user == "%d:%d" % (os.getuid(), os.getgid())


def test_the_application_s_names_are_what_its_container_may_run(part, docker):
    external.open_file(str(part), use_docker=True)
    assert docker.spec.allowed_commands == {name: None for name in external.TOOLS["freecad"].binaries}


def test_a_container_without_the_application_is_refused_with_the_way_out(part, docker):
    docker.binaries = []
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "--docker-image" in str(caught.value)
    assert external.TOOLS["freecad"].image in str(caught.value)


def test_the_application_is_run_in_the_container_on_the_host_file(part, docker):
    external.open_file(str(part), use_docker=True, mode="mount")
    assert docker.last["command"] == ["freecad", str(part)]
    assert docker.last["env"]["DISPLAY"] == ":0"
    # Until it is closed: that is what lets what was done in it be brought back.
    assert docker.last["timeout"] is None


def test_a_file_outside_this_workspace_still_gets_a_mount_that_holds_it(tmp_path, docker, monkeypatch):
    # Whatever is mounted has to contain the file, or the application would be
    # handed a name the container cannot resolve. The workspace `pc ide open` runs
    # in is preferred -- it is the one with a daemon -- but it is not imposed.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = elsewhere / "cube.step"
    outside.write_text("ISO-10303-21;\n")

    external.open_file(str(outside), use_docker=True, mode="mount")
    assert _visible(docker.spec, outside)
    assert not _visible(docker.spec, workspace)


def test_the_workspace_the_command_runs_in_is_the_one_mounted(part, docker, monkeypatch, tmp_path):
    nested = tmp_path / "parts"
    nested.mkdir()
    monkeypatch.chdir(nested)
    external.open_file(str(part), use_docker=True, mode="mount")
    assert _visible(docker.spec, tmp_path)


def test_a_command_the_container_refused_is_reported_with_what_it_said(part, docker):
    docker.exit_code = 1
    docker.stderr = "The 'partcad-open-freecad' container refused the command: exec failed"
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "exec failed" in str(caught.value)


def test_an_application_that_exits_unhappily_is_not_a_failure_to_open(part, docker):
    """It opened, it was used, it closed: how it closed is the application's business."""
    docker.exit_code = 1
    result = external.open_file(str(part), use_docker=True)
    assert result.method == "docker"


# ---------------------------------------------------------------------------
# 'upload' mode: the file goes with the command and comes back
# ---------------------------------------------------------------------------


def test_upload_mode_mounts_nothing_and_sends_the_file_both_ways(part, docker):
    external.open_file(str(part), use_docker=True, mode="upload")
    from partcad_utils import containers

    assert docker.spec.mode == containers.UPLOAD
    assert docker.spec.mounts == {}
    assert docker.last["input_files"] == [str(part)]
    assert docker.last["output_files"] == [str(part)]


def test_upload_mode_runs_as_the_image_s_user(part, docker):
    external.open_file(str(part), use_docker=True, mode="upload")
    assert docker.spec.user is None


def test_upload_mode_sends_a_project_s_whole_directory(monkeypatch, docker, tmp_path):
    """KiCad saves the board beside the project it opened: the directory is what was edited."""
    (tmp_path / "partcad.yaml").write_text("name: t\n")
    (tmp_path / "board.step").write_text("ISO-10303-21;\n")
    (tmp_path / "board.kicad_pro").write_text("{}")
    docker.binaries = ["kicad"]
    external.open_file(str(tmp_path / "board.step"), tool="kicad", use_docker=True, mode="upload")
    assert docker.last["input_dirs"] == [str(tmp_path)]
    assert docker.last["output_dirs"] == [str(tmp_path)]


def test_a_file_name_quoted_inside_an_argument_cannot_be_sent(monkeypatch, docker, part):
    previous = dict(external.TOOLS)
    external.use_tools(
        {"quoter": {"binaries": ["quoter"], "image": "x/quoter:1", "fileArgs": ["-c", "open({path_repr})"]}}
    )
    docker.binaries = ["quoter"]
    try:
        with pytest.raises(external.ExternalToolError) as caught:
            external.open_file(str(part), tool="quoter", use_docker=True, mode="upload")
        assert "{path}" in str(caught.value)
    finally:
        external.TOOLS.clear()
        external.TOOLS.update(previous)


def test_the_display_s_plumbing_is_kept_in_upload_mode(part, docker, monkeypatch):
    """The X socket is not how files arrive; `containers.acquire` drops it only for another machine's daemon."""
    real_isdir = external.os.path.isdir
    monkeypatch.setattr(external.os.path, "isdir", lambda path: True if path == "/tmp/.X11-unix" else real_isdir(path))
    external.open_file(str(part), use_docker=True, mode="upload")
    assert "/tmp/.X11-unix" in docker.spec.local_binds


# ---------------------------------------------------------------------------
# Getting the window onto the user's screen
# ---------------------------------------------------------------------------


def test_linux_shares_the_x_socket_and_the_display(part, docker, monkeypatch):
    # The display is a socket on this machine, so the container gets the socket
    # rather than instructions for setting up an X server.
    real_isdir = external.os.path.isdir
    monkeypatch.setattr(external.os.path, "isdir", lambda path: True if path == "/tmp/.X11-unix" else real_isdir(path))
    external.open_file(str(part), use_docker=True)
    assert docker.spec.local_binds["/tmp/.X11-unix"] == {"bind": "/tmp/.X11-unix", "mode": "rw"}
    assert docker.last["env"]["DISPLAY"] == ":0"


def test_linux_passes_the_x_cookie_as_well_as_the_socket(part, docker, monkeypatch, tmp_path):
    # The file *and* the variable naming it: an X client that cannot find the
    # cookie is refused by the server, and the container's home directory is not
    # the user's.
    cookie = tmp_path / "Xauthority"
    cookie.write_text("cookie")
    monkeypatch.setenv("XAUTHORITY", str(cookie))
    external.open_file(str(part), use_docker=True)
    assert docker.spec.local_binds[str(cookie)] == {"bind": str(cookie), "mode": "ro"}
    assert docker.last["env"]["XAUTHORITY"] == str(cookie)


def test_a_forwarded_linux_display_is_reached_over_the_host_gateway(part, docker, monkeypatch):
    # An SSH-forwarded display is TCP, not a socket: there is nothing to share,
    # so the container is told where the host is instead.
    monkeypatch.setenv("DISPLAY", "localhost:10.0")
    external.open_file(str(part), use_docker=True)
    assert docker.last["env"]["DISPLAY"] == "host.docker.internal:10.0"
    assert docker.spec.extra_hosts == {"host.docker.internal": "host-gateway"}


def test_linux_without_a_display_says_so_before_creating_anything(part, docker, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "DISPLAY" in str(caught.value)
    assert docker.specs == []


def test_macos_without_an_x_server_names_the_one_to_install(part, docker, monkeypatch):
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(external, "_xquartz_installed", lambda: False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "XQuartz" in str(caught.value)
    assert docker.specs == []


def test_macos_reaches_the_host_x_server_over_tcp(part, docker, monkeypatch):
    # The launchd socket macOS puts in DISPLAY means nothing inside a container.
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("DISPLAY", "/private/tmp/com.apple.launchd.7Uu/org.xquartz:0")
    monkeypatch.setattr(external, "_xquartz_installed", lambda: True)
    result = external.open_file(str(part), use_docker=True)
    assert docker.last["env"]["DISPLAY"] == "host.docker.internal:0"
    assert "xhost" in result.detail


def test_windows_without_a_display_names_the_x_servers_to_install(part, docker, monkeypatch):
    monkeypatch.setattr(external.platform, "system", lambda: "Windows")
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "VcXsrv" in str(caught.value)
    assert docker.specs == []


@pytest.mark.parametrize(
    "display, expected",
    [
        (":0", "host.docker.internal:0"),
        ("localhost:0", "host.docker.internal:0"),
        ("127.0.0.1:1", "host.docker.internal:1"),
        ("/private/tmp/com.apple.launchd.7Uu/org.xquartz:0", "host.docker.internal:0"),
        ("workstation.local:0", "workstation.local:0"),
    ],
)
def test_a_local_display_is_readdressed_for_the_container(display, expected):
    assert external._host_display(display) == expected


def test_the_result_says_how_the_file_was_opened(part, docker):
    result = external.open_file(str(part), use_docker=True)
    assert result.to_dict()["ok"] is True
    assert result.to_dict()["method"] == "docker"
    assert result.to_dict()["path"] == str(part)


# ---------------------------------------------------------------------------
# The other applications in the table
# ---------------------------------------------------------------------------


# The `open:` entries the two engine plugins declare, copied here as a package
# supplies them. They are not in the wheel: `partcad/partcad-sim-gazebo` and
# `partcad/partcad-sim-mujoco` own the engine, its scene format, the exporter,
# the reader and this entry alike.
#
# The tests below drive the machinery through these rather than through a
# built-in entry, which is the arrangement that has to keep working -- and a
# stronger check than the one it replaces, since it proves a declared tool
# reaches every part of the launcher a shipped one does.
GAZEBO_DECLARATION = {
    "displayName": "Gazebo",
    "image": "gazebosim/gz-harmonic:latest",
    "binaries": ["gz", "ign", "gazebo"],
    "binaryArgs": {"gz": ["sim"], "ign": ["gazebo"]},
    "macosApps": ["Gazebo.app"],
    "windowsGlobs": ["Gazebo*/bin/gz.exe"],
    "flatpakId": "org.gazebosim.Gazebo",
}

MUJOCO_DECLARATION = {
    "displayName": "MuJoCo",
    "image": "ghcr.io/google-deepmind/mujoco:latest",
    "binaries": ["simulate", "mujoco"],
    "macosApps": ["MuJoCo.app"],
    "macosExecutable": "Contents/MacOS/simulate",
    "windowsGlobs": ["MuJoCo*/bin/simulate.exe", "mujoco*/bin/simulate.exe"],
    "sceneType": "mjcf",
    "sceneExtensions": [".xml", ".mjcf"],
}


@pytest.fixture
def engines():
    """The two engine plugins' applications, declared into this process.

    Exactly what `pc ide open` does with what the daemon reports a workspace's
    packages declare, and undone afterwards so that a test which does not ask
    for them sees the wheel's own table.
    """
    previous = dict(external.TOOLS)
    external.use_tools({"gazebo": GAZEBO_DECLARATION, "mujoco": MUJOCO_DECLARATION})
    try:
        yield
    finally:
        external.TOOLS.clear()
        external.TOOLS.update(previous)


def test_every_tool_can_be_named_and_has_a_container_of_its_own():
    """What the wheel itself ships: no engine, because no engine is PartCAD's."""
    assert set(external.tool_names()) == {"freecad", "kicad", "blender"}
    roles = {external.TOOLS[name].role for name in external.tool_names()}
    assert roles == {"open-freecad", "open-kicad", "open-blender"}


def test_an_application_a_package_declares_joins_the_ones_that_ship(engines):
    """Which is how `pc ide open --with mujoco` works at all now."""
    assert set(external.tool_names()) == {"freecad", "kicad", "blender", "gazebo", "mujoco"}
    assert external.TOOLS["mujoco"].role == "open-mujoco"
    assert external.TOOLS["gazebo"].role == "open-gazebo"


def test_the_kicad_container_is_the_image_partcad_already_builds(external_at_release):
    """One KiCad container in the product, not two.

    'partcad.part_factory_kicad' pulls the same image, pinned to the same
    release, to run 'kicad-cli' in. Pinning matters here as much as it does
    there: the container carries PartCAD's own environment.

    Asserted of an installed PartCAD, where nothing overrides the tag, which is
    the whole of what 'external_at_release' arranges -- this module reads the
    tag once, as it is imported, so the variable has to be gone before the
    import rather than during the test. The dance used to be written out here;
    it is in 'tests/conftest.py' because the test that arrived beside it in the
    'open:' section needs the same thing, and did not have it.

    'tests/partcad_utils/test_container_image.py' pins the other direction,
    where the override is set and this module has to follow it.
    """
    from partcad_client import __version__

    image = external_at_release.TOOLS["kicad"].image

    assert image == "ghcr.io/partcad/partcad-container-kicad:" + __version__


@pytest.fixture
def world(tmp_path):
    """A Gazebo world inside a workspace."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "warehouse.world"
    path.write_text('<sdf version="1.9"><world name="warehouse"/></sdf>\n')
    return path


@pytest.mark.parametrize(
    "binary, expected",
    [
        ("gz", ["sim"]),
        ("ign", ["gazebo"]),
        ("gazebo", []),
    ],
)
def test_each_generation_of_gazebo_is_launched_the_way_it_wants(monkeypatch, spawned, world, binary, expected, engines):
    """`gz sim`, `ign gazebo` and plain `gazebo` are one application, three front ends."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name if name == binary else None)

    result = external.open_file(str(world), tool="gazebo")

    assert result.method == "native"
    assert spawned == [["/usr/bin/" + binary] + expected + [str(world)]]


def test_gazebo_runs_in_its_own_container_with_the_world_file(world, docker, engines):
    docker.binaries = ["gz"]

    result = external.open_file(str(world), tool="gazebo", use_docker=True, mode="mount")

    assert result.method == "docker"
    assert docker.spec.role == "open-gazebo"
    assert docker.spec.image == external.TOOLS["gazebo"].image
    # The arguments the executable found *inside* the container needs, not the
    # ones the host would have needed.
    assert docker.last["command"] == ["gz", "sim", str(world)]


def test_kicad_opens_the_board_beside_the_step_a_part_points_at(monkeypatch, spawned, tmp_path):
    """A `kicad` part *is* the STEP KiCad's CLI writes; the board is next to it."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    step = tmp_path / "Arduino_Nano.step"
    step.write_text("ISO-10303-21;\n")
    project = tmp_path / "Arduino_Nano.kicad_pro"
    project.write_text("{}\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/kicad" if name == "kicad" else None)

    result = external.open_file(str(step), tool="kicad")

    assert result.path == str(project)
    assert spawned == [["/usr/bin/kicad", str(project)]]


def test_kicad_falls_back_through_the_board_files_it_knows(monkeypatch, spawned, tmp_path):
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    step = tmp_path / "board.step"
    step.write_text("ISO-10303-21;\n")
    (tmp_path / "board.kicad_pcb").write_text("(kicad_pcb)\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/kicad" if name == "kicad" else None)

    external.open_file(str(step), tool="kicad")

    assert spawned == [["/usr/bin/kicad", str(tmp_path / "board.kicad_pcb")]]


def test_a_board_file_named_outright_is_the_one_opened(monkeypatch, spawned, tmp_path):
    """Only a file KiCad cannot open is swapped; one it can is left alone."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)\n")
    (tmp_path / "board.kicad_pro").write_text("{}\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/kicad" if name == "kicad" else None)

    external.open_file(str(board), tool="kicad")

    assert spawned == [["/usr/bin/kicad", str(board)]]


def test_a_step_with_no_board_beside_it_is_refused_rather_than_handed_over(monkeypatch, spawned, part):
    """KiCad opens a project and its two files; PartCAD writes none of them, so there is nothing to convert to.

    It used to be handed the STEP anyway and left to say what it thought of it.
    """
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/kicad" if name == "kicad" else None)

    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="kicad")

    assert "KICAD_PRO" in str(caught.value)
    assert spawned == []


def test_only_the_tool_that_declares_companions_swaps_the_file(monkeypatch, spawned, tmp_path):
    """FreeCAD opens the STEP it was handed, board or no board beside it."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    step = tmp_path / "board.step"
    step.write_text("ISO-10303-21;\n")
    (tmp_path / "board.kicad_pro").write_text("{}\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/freecad" if name == "freecad" else None)

    external.open_file(str(step), tool="freecad")

    assert spawned == [["/usr/bin/freecad", str(step)]]


def test_a_launcher_that_is_not_the_program_supplies_its_own_arguments():
    """macOS's `open -a` and `flatpak run` bundle one front end and know it.

    `binary_args` is keyed on the program's own name, so neither matches -- and
    neither should: adding `sim` to a `flatpak run org.gazebosim.Gazebo` would
    hand it to the flatpak's entry point rather than to `gz`.
    """
    gazebo = external.tool_from_declaration("gazebo", GAZEBO_DECLARATION)

    # The Windows form is spelled with the separator this platform uses, since
    # that is what `native_command()` builds it with there.
    assert gazebo.launch_args("/usr/bin/gz") == ("sim",)
    assert gazebo.launch_args(os.path.join("Gazebo", "bin", "gz.exe")) == ("sim",)
    assert gazebo.launch_args("org.gazebosim.Gazebo") == ()
    assert gazebo.launch_args("/Applications/Gazebo.app") == ()


# ---------------------------------------------------------------------------
# Blender: the application that reads meshes and nothing else
# ---------------------------------------------------------------------------


@pytest.fixture
def mesh(tmp_path):
    """An STL inside a workspace: what Blender can be handed as it is."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "cube.stl"
    path.write_text("solid cube\nendsolid cube\n")
    return path


@pytest.fixture
def converter():
    """A conversion that writes the file it was asked for, and records the ask."""

    class Converter:
        def __init__(self):
            self.calls = []
            # Which kind of object each conversion was of: "part" for the mesh a
            # Blender open needs, "scene" for the MJCF a MuJoCo open needs.
            self.kinds = []
            self.writes = True

        def __call__(self, source, source_type, target, target_type, kind="part"):
            self.calls.append((source, source_type, target, target_type))
            self.kinds.append(kind)
            if self.writes:
                open(target, "w").write("solid converted\nendsolid converted\n")

    return Converter()


def test_a_mesh_is_imported_rather_than_opened(monkeypatch, spawned, mesh):
    """`blender <file>` opens a `.blend`; anything else is an import, in Python."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    result = external.open_file(str(mesh), tool="blender")

    assert result.method == "native"
    assert result.path == str(mesh)
    # Nothing was converted, so there is nothing to report as converted from.
    assert result.source is None
    command = spawned[0]
    assert command[:2] == ["/usr/bin/blender", "--python-expr"]
    assert "stl_import" in command[2]
    # The name is an argument of its own, after '--' -- which is what lets it
    # be sent to a container that does not share this machine's files.
    assert command[-2:] == ["--", str(mesh)]


def test_blender_s_own_file_is_opened_and_never_converted(monkeypatch, spawned, tmp_path, converter):
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    scene = tmp_path / "scene.blend"
    scene.write_text("BLENDER")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    external.open_file(str(scene), tool="blender", transcode=converter)

    assert spawned == [["/usr/bin/blender", str(scene)]]
    assert converter.calls == []


def test_a_solid_is_converted_to_a_mesh_first(monkeypatch, spawned, part, converter, workspace_socket):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    result = external.open_file(str(part), tool="blender", transcode=converter)

    # The conversion is asked for by type, not left to be guessed at the far end.
    source, source_type, target, target_type = converter.calls[0]
    assert (source, source_type, target_type) == (str(part), "step", "stl")
    # It lands under the workspace's own directory -- not beside the user's
    # file, and not in a temporary directory the container cannot see.
    assert target.startswith(str(workspace_socket))
    assert result.path == target
    assert result.source == str(part)
    assert spawned[0][-1] == target


def test_the_converted_mesh_is_reused_until_the_source_changes(monkeypatch, spawned, part, converter):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    first = external.open_file(str(part), tool="blender", transcode=converter)
    second = external.open_file(str(part), tool="blender", transcode=converter)
    assert second.path == first.path
    assert len(converter.calls) == 1

    # Touching the source is how a user asks for it again.
    os.utime(str(part), (os.path.getmtime(first.path) + 10,) * 2)
    external.open_file(str(part), tool="blender", transcode=converter)
    assert len(converter.calls) == 2


def test_two_parts_of_the_same_name_do_not_share_a_mesh(monkeypatch, spawned, part, converter, tmp_path):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)
    other = tmp_path / "elsewhere"
    other.mkdir()
    twin = other / "cube.step"
    twin.write_text("ISO-10303-21;\n")

    first = external.open_file(str(part), tool="blender", transcode=converter)
    second = external.open_file(str(twin), tool="blender", transcode=converter)

    assert first.path != second.path


def test_a_conversion_that_writes_nothing_is_a_failure_not_a_window(monkeypatch, spawned, part, converter):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)
    converter.writes = False

    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="blender", transcode=converter)

    assert "Failed to convert" in str(caught.value)
    assert spawned == []


def test_a_mesh_blender_has_no_importer_for_is_converted_too(monkeypatch, spawned, tmp_path, converter):
    """3MF is a mesh, and Blender ships nothing that reads one."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    box = tmp_path / "box.3mf"
    box.write_text("PK\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    external.open_file(str(box), tool="blender", transcode=converter)

    source, source_type, _target, target_type = converter.calls[0]
    assert (source, source_type, target_type) == (str(box), "3mf", "stl")


def test_a_declared_type_says_what_the_file_name_cannot(monkeypatch, spawned, tmp_path, converter):
    """A '.py' is a CadQuery script, a build123d one or an SDF one."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    script = tmp_path / "cube.py"
    script.write_text("# a part\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    external.open_file(str(script), tool="blender", object_type="build123d", transcode=converter)

    assert converter.calls[0][1] == "build123d"


def test_a_declared_type_that_is_not_a_format_does_not_become_one(monkeypatch, spawned, part, converter):
    """A `kicad` part is the STEP that KiCad's CLI wrote; it is read as a STEP.

    The tree hands over whatever the object was declared as, and several of
    those types name no file format at all. Sending one as the input type would
    ask the daemon to read a STEP file as a KiCad board.
    """
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    external.open_file(str(part), tool="blender", object_type="kicad", transcode=converter)

    assert converter.calls[0][1] == "step"


def test_a_file_whose_type_cannot_be_told_is_refused_with_what_to_pass(monkeypatch, spawned, tmp_path, converter):
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    script = tmp_path / "cube.py"
    script.write_text("# a part\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(script), tool="blender", transcode=converter)

    assert "--type" in str(caught.value)
    assert "cadquery" in str(caught.value)
    assert converter.calls == []


def test_an_assy_is_refused_by_name_rather_than_sent_to_be_refused(monkeypatch, spawned, tmp_path, converter):
    """There is no package around an ad-hoc file to resolve an ASSY against."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    assembly = tmp_path / "logo.assy"
    assembly.write_text("links: []\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(assembly), tool="blender", transcode=converter)

    assert "inside a package" in str(caught.value)
    assert "pc export" in str(caught.value)
    assert converter.calls == []


def test_without_a_converter_a_solid_says_so_instead_of_opening_nothing(monkeypatch, spawned, part):
    """Nothing but `pc ide open` has a daemon to convert with, and it says which."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/blender" if name == "blender" else None)

    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="blender")

    assert "pc ide open" in str(caught.value)
    assert spawned == []


def test_blender_runs_in_its_own_container_on_the_converted_mesh(part, docker, converter, workspace_socket):
    docker.binaries = ["blender"]

    result = external.open_file(str(part), tool="blender", use_docker=True, transcode=converter, mode="mount")

    assert result.method == "docker"
    assert docker.spec.role == "open-blender"
    assert docker.spec.image == external.TOOLS["blender"].image
    # The workspace that holds the *source* is what gets mounted: the mesh lives
    # under that workspace's state directory, and a workspace worked out from
    # the mesh would have been the state directory.
    assert _visible(docker.spec, workspace_socket)
    assert docker.last["command"][:2] == ["blender", "--python-expr"]
    assert docker.last["command"][-1] == result.path


def test_a_solid_without_docker_or_blender_says_both(part, converter):
    """The refusal a machine with neither gets, which has to name both ways out."""
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="blender", transcode=converter)
    assert "Blender was not found" in str(caught.value)
    assert "--use-docker" in str(caught.value)


def test_docker_that_does_not_answer_names_blender_and_docker(part, docker, converter):
    docker.available = False
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), tool="blender", use_docker=True, transcode=converter)
    assert "Blender is not installed" in str(caught.value)
    assert "docker info" in str(caught.value)


def test_macos_runs_the_executable_inside_the_bundle(monkeypatch):
    """`open -a` hands a running Blender nothing at all, and the arguments are the point.

    The two paths are built with `os.path.join`, the way `native_command` builds
    them, rather than spelled out with slashes. This test runs on every platform
    -- including Windows, where `os.path.join` uses a backslash, so a hand-spelled
    "/Applications/Blender.app" is not the string the code under test compares
    against and the mocked `isdir` never matches.
    """
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(external.shutil, "which", lambda _name: None)
    bundle = os.path.join("/Applications", "Blender.app")
    executable = os.path.join(bundle, external.TOOLS["blender"].macos_executable)
    monkeypatch.setattr(external.os.path, "isdir", lambda path: path == bundle)
    monkeypatch.setattr(external.os.path, "isfile", lambda path: path == executable)

    assert external.native_command(external.TOOLS["blender"]) == [executable]


def test_macos_opens_the_bundle_for_an_application_that_takes_a_file(monkeypatch):
    """The other half of that rule, and the one every other tool takes.

    FreeCAD is handed a document rather than arguments, so `open -a` is right
    for it -- with '-W', so that `pc ide open` waits for it to close, and '-n', so
    that what it waits for is this copy and not one that was already running.
    """
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(external.shutil, "which", lambda _name: None)
    bundle = os.path.join("/Applications", "FreeCAD.app")
    monkeypatch.setattr(external.os.path, "isdir", lambda path: path == bundle)

    assert external.native_command(external.TOOLS["freecad"]) == ["open", "-W", "-n", "-a", bundle]


def test_a_bundle_without_the_executable_in_it_is_not_a_local_installation(monkeypatch):
    """A `Blender.app` with nothing runnable inside is not something to launch.

    Falling back to `open -a` here would be worse than finding nothing: the
    import expression would be dropped and Blender would open empty, which
    looks like PartCAD doing nothing at all. Finding nothing is honest, and
    leaves the container route to say what to install.
    """
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(external.shutil, "which", lambda _name: None)
    monkeypatch.setattr(external.os.path, "isdir", lambda path: path.endswith("Blender.app"))
    monkeypatch.setattr(external.os.path, "isfile", lambda _path: False)

    assert external.native_command(external.TOOLS["blender"]) is None


def test_the_other_applications_are_still_handed_the_file_itself(monkeypatch, spawned, part):
    """Only Blender imports; converting for FreeCAD would be a loss, not a favour."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name if name == "freecad" else None)
    external.open_file(str(part), tool="freecad")
    assert spawned == [["/usr/bin/freecad", str(part)]]


# ---------------------------------------------------------------------------
# MuJoCo: an application that reads one scene description and no other
# ---------------------------------------------------------------------------


@pytest.fixture
def mjcf(tmp_path):
    """An MJCF model inside a workspace: what MuJoCo reads as it is."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "stack.xml"
    path.write_text('<mujoco model="stack"><worldbody/></mujoco>\n')
    return path


def test_mujoco_opens_its_own_model_without_converting_anything(monkeypatch, spawned, mjcf, converter, engines):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    result = external.open_file(str(mjcf), tool="mujoco", transcode=converter)

    assert result.method == "native"
    assert result.source is None
    assert spawned == [["/usr/bin/simulate", str(mjcf)]]
    assert converter.calls == []


def test_a_world_cannot_be_made_into_a_model_with_no_package_to_do_it(monkeypatch, world, converter, engines):
    """A Gazebo world handed to MuJoCo is a file MuJoCo cannot read -- and PartCAD
    cannot make one it can, here.

    Writing MJCF is `partcad/partcad-sim-mujoco`'s exporter, and reading the
    world is `partcad/partcad-sim-gazebo`'s reader. An ad-hoc conversion has a
    throwaway package around the file and no dependency on either, so it cannot
    run one -- which is why this refuses rather than converting, and says which
    export does work.
    """
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(world), tool="mujoco", transcode=converter)

    message = str(error.value)
    assert "MJCF" in message
    # The advice has to name a package, because a bare 'mjcf' resolves to
    # nothing now.
    assert "pc export -S -t <package>:mjcf" in message
    # Nothing was attempted: a conversion that cannot work must not be started.
    assert converter.calls == []


def test_a_model_by_any_name_is_opened_once_its_type_is_declared(monkeypatch, spawned, tmp_path, converter, engines):
    """The VS Code tree knows the declared type; a name like '.sdf' does not.

    And the declared type arrives qualified -- 'sim-mujoco:mjcf' -- because that
    is how a package that is not the plugin has to write it. Comparing it with
    the bare 'mjcf' the plugin's own `open:` entry names is what makes those one
    format rather than two.
    """
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "stack.model"
    path.write_text('<mujoco model="stack"><worldbody/></mujoco>\n')
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    result = external.open_file(str(path), tool="mujoco", object_type="sim-mujoco:mjcf", transcode=converter)

    assert result.method == "native"
    assert result.source is None
    assert spawned == [["/usr/bin/simulate", str(path)]]
    assert converter.calls == []


def test_an_assy_scene_is_refused_by_name_rather_than_converted(monkeypatch, tmp_path, converter, engines):
    """It is nothing but references to the parts of a package."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "bench.assy"
    path.write_text("links: []\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(path), tool="mujoco", transcode=converter)

    assert "only means anything inside a package" in str(error.value)
    assert "pc export -S -t <package>:mjcf" in str(error.value)
    assert converter.calls == []


def test_a_file_that_is_no_scene_at_all_says_so(monkeypatch, part, converter, engines):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(part), tool="mujoco", transcode=converter)

    assert "MJCF" in str(error.value)
    assert converter.calls == []


def test_another_engines_format_is_refused_even_in_this_one_s_extension(monkeypatch, tmp_path, converter, engines):
    """The declared type wins over the file name, and has to.

    Two scene formats can be stored in one extension -- SDFormat and MJCF are
    both XML -- so a '.xml' says nothing on its own. Reading the extension first
    would hand MuJoCo a Gazebo world and let it say something of its own, which
    is the exact failure `_transcode_scene` exists to prevent. Found by
    CodeRabbit on this PR; the '.sdf' case below did not cover it, because that
    extension collides with nothing.
    """
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "warehouse.xml"
    path.write_text('<sdf version="1.9"><world name="warehouse"/></sdf>\n')
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(path), tool="mujoco", object_type="sim-gazebo:world", transcode=converter)

    assert "MJCF" in str(error.value)
    assert converter.calls == []


def test_an_assy_in_this_engine_s_extension_is_refused_as_an_assy(monkeypatch, tmp_path, converter, engines):
    """The same rule for the one scene format PartCAD itself has.

    'assy' is not qualified, so it is not "some package declared it" -- it is in
    `object_types.SCENE_TYPE_EXTENSION`, which is how a bare name is known to
    name a format at all. It is also package-only, so the refusal is the ASSY
    one rather than the general one.
    """
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "bench.xml"
    path.write_text("links: []\n")
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(path), tool="mujoco", object_type="assy", transcode=converter)

    assert "only means anything inside a package" in str(error.value)
    assert converter.calls == []


def test_a_type_that_names_no_format_still_defers_to_the_file(monkeypatch, spawned, tmp_path, converter, engines):
    """What must NOT be refused: a declared type that says nothing about the file.

    An 'alias' is a reference, not a format, so it cannot contradict the name --
    the same rule `readable_scene_type` applies. Getting this wrong in the other
    direction would refuse a file the application reads perfectly well.
    """
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "stack.xml"
    path.write_text('<mujoco model="stack"><worldbody/></mujoco>\n')
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    result = external.open_file(str(path), tool="mujoco", object_type="alias", transcode=converter)

    assert result.method == "native"
    assert spawned == [["/usr/bin/simulate", str(path)]]
    assert converter.calls == []


def test_a_declared_type_for_another_engine_is_still_refused(monkeypatch, tmp_path, converter, engines):
    """Saying what the file is does not make it something MuJoCo reads."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "warehouse.sdf"
    path.write_text('<sdf version="1.9"><world name="warehouse"/></sdf>\n')
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/simulate" if name == "simulate" else None)

    with pytest.raises(external.ExternalToolError) as error:
        external.open_file(str(path), tool="mujoco", object_type="sim-gazebo:world", transcode=converter)

    assert "MJCF" in str(error.value)
    assert converter.calls == []


def test_mujoco_runs_in_its_own_container_with_the_model(mjcf, docker, engines):
    docker.binaries = ["simulate"]

    result = external.open_file(str(mjcf), tool="mujoco", use_docker=True, mode="mount")

    assert result.method == "docker"
    assert docker.spec.role == "open-mujoco"
    assert docker.last["command"][-1] == str(mjcf)


# ---------------------------------------------------------------------------
# `open:` plugins: what an application opens, and what comes back
# ---------------------------------------------------------------------------


def _installed(monkeypatch, *names):
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name if name in names else None)


@pytest.fixture
def script(tmp_path):
    """A CadQuery part: a file, and not one any application opens or PartCAD can write back into."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "bracket.py"
    path.write_text("import cadquery as cq\nshow_object(cq.Workplane().box(1, 1, 1))\n")
    return path


@pytest.fixture
def printed(tmp_path):
    """A 3MF part: a mesh Blender has no importer for, and a format PartCAD writes."""
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "cube.3mf"
    path.write_bytes(b"3MF original")
    return path


def _edits(path_index=-1, content="edited"):
    """What a user does in the application: write to the file it was given, and close it."""

    def edit(command):
        with open(command[path_index], "a") as f:
            f.write("\n" + content)

    return edit


def test_an_object_on_the_list_is_opened_as_it_is(monkeypatch, spawned, part, converter):
    _installed(monkeypatch, "freecad")
    result = external.open_file(str(part), tool="freecad", transcode=converter)
    assert converter.calls == []
    assert result.path == str(part)
    assert spawned[0][-1] == str(part)


def test_an_object_off_the_list_becomes_the_first_format_partcad_writes(monkeypatch, spawned, script, converter):
    """A CadQuery script for FreeCAD arrives as the solid it is: STEP, the first writable format on its list."""
    _installed(monkeypatch, "freecad")
    result = external.open_file(str(script), tool="freecad", object_type="cadquery", transcode=converter)
    assert converter.calls[0][1:2] == ("cadquery",)
    assert converter.calls[0][3] == "step"
    assert result.path.endswith(".step")


def test_a_format_partcad_cannot_write_is_passed_over_for_the_next(monkeypatch, spawned, part, converter):
    """Blender's list starts with its own '.blend', which nothing converts into; STL is next."""
    _installed(monkeypatch, "blender")
    external.open_file(str(part), tool="blender", transcode=converter)
    assert converter.calls[0][3] == "stl"


def test_pc_open_waits_for_the_application_to_close(monkeypatch, part):
    _installed(monkeypatch, "freecad")
    order = []
    monkeypatch.setattr(external, "_launch", lambda args: order.append("application closed") or 0)
    external.open_file(str(part), tool="freecad")
    order.append("pc ide open returned")
    assert order == ["application closed", "pc ide open returned"]


def test_nothing_changed_is_nothing_written(monkeypatch, spawned, part, converter):
    _installed(monkeypatch, "freecad")
    result = external.open_file(str(part), tool="freecad", transcode=converter)
    assert result.changed is False
    assert result.written_back is None and result.edited is None


def test_an_edit_to_an_object_opened_as_it_is_is_already_where_it_lives(monkeypatch, spawned, part, converter):
    _installed(monkeypatch, "freecad")
    spawned.edit = _edits()
    result = external.open_file(str(part), tool="freecad", transcode=converter)
    assert result.changed is True
    assert result.written_back == str(part)
    assert "edited" in part.read_text()
    assert converter.calls == []


def test_an_edit_to_a_converted_copy_is_converted_back_over_the_source(monkeypatch, spawned, printed, converter):
    """The 3MF went to Blender as STL; the edited STL comes back as 3MF, over the 3MF."""
    _installed(monkeypatch, "blender")
    spawned.edit = _edits()
    result = external.open_file(str(printed), tool="blender", transcode=converter)
    copy = result.path
    assert result.changed is True
    assert converter.calls[-1] == (copy, "stl", str(printed), "3mf")
    assert result.written_back == str(printed)
    assert result.edited is None


def test_an_edit_to_a_script_s_copy_is_kept_and_reported_not_written_over_the_script(
    monkeypatch, spawned, script, converter
):
    """A STEP cannot become CadQuery again: the script is left alone and the edited STEP is said to be where it is."""
    _installed(monkeypatch, "freecad")
    spawned.edit = _edits()
    before = script.read_text()
    result = external.open_file(str(script), tool="freecad", object_type="cadquery", transcode=converter)
    assert result.changed is True
    assert result.written_back is None
    assert result.edited == result.path
    assert script.read_text() == before
    assert len(converter.calls) == 1  # there and not back


def test_a_failed_conversion_back_keeps_the_edit_and_says_so(monkeypatch, spawned, printed):
    _installed(monkeypatch, "blender")
    spawned.edit = _edits()
    calls = []

    def transcode(source, source_type, target, target_type, kind="part"):
        calls.append(target_type)
        if len(calls) > 1:
            raise RuntimeError("the daemon went away")
        open(target, "w").write("solid\nendsolid\n")

    result = external.open_file(str(printed), tool="blender", transcode=transcode)
    assert result.written_back is None
    assert result.edited == result.path
    assert "the daemon went away" in result.detail
    assert printed.read_bytes() == b"3MF original"


def test_a_project_is_watched_as_a_whole(monkeypatch, spawned, tmp_path):
    """KiCad opens the project and saves the board beside it."""
    _installed(monkeypatch, "kicad")
    (tmp_path / "partcad.yaml").write_text("name: t\n")
    (tmp_path / "board.step").write_text("ISO-10303-21;\n")
    (tmp_path / "board.kicad_pro").write_text("{}")
    board = tmp_path / "board.kicad_pcb"
    board.write_text("v1")
    spawned.edit = lambda command: board.write_text("v2")
    result = external.open_file(str(tmp_path / "board.step"), tool="kicad")
    assert result.changed is True
    assert result.written_back == str(tmp_path)


def test_an_application_that_returns_at_once_having_changed_nothing_is_said_to_have(monkeypatch, spawned, part):
    """It most likely handed the file to a copy already running; edits made there will not come back."""
    _installed(monkeypatch, "freecad")
    result = external.open_file(str(part), tool="freecad")
    assert "returned at once" in result.detail


def test_an_edit_made_in_a_container_in_upload_mode_comes_back(part, docker):
    """What `Endpoint.result` does with the file the service sent back, as far as `pc ide open` can tell."""
    docker.edit = lambda command: open(command[-1], "a").write("\nedited in the container")
    result = external.open_file(str(part), use_docker=True, mode="upload")
    assert result.changed is True
    assert result.written_back == str(part)


def test_the_result_says_what_became_of_the_edit(monkeypatch, spawned, printed, converter):
    _installed(monkeypatch, "blender")
    spawned.edit = _edits()
    answer = external.open_file(str(printed), tool="blender", transcode=converter).to_dict()
    assert answer["changed"] is True
    assert answer["writtenBack"] == str(printed)
    assert answer["edited"] is None


# ---------------------------------------------------------------------------
# What a declaration says
# ---------------------------------------------------------------------------


def test_a_container_is_declared_the_way_a_plugin_s_implementation_declares_one():
    tool = external.tool_from_declaration(
        "x", {"container": {"image": "ghcr.io/x/app:1", "python": "/opt/py/bin/python3"}}
    )
    assert tool.image == "ghcr.io/x/app:1"
    assert tool.container_python == "/opt/py/bin/python3"


def test_a_container_may_be_named_by_its_image_alone():
    assert external.tool_from_declaration("x", {"container": "ghcr.io/x/app:1"}).image == "ghcr.io/x/app:1"


def test_the_older_image_field_still_names_the_container():
    assert external.tool_from_declaration("x", {"image": "ghcr.io/x/app:1"}).image == "ghcr.io/x/app:1"


def test_the_older_format_fields_become_formats_in_the_order_they_meant():
    tool = external.tool_from_declaration(
        "x", {"ownFormats": [".blend"], "meshVia": "stl", "imports": [".stl", ".obj"], "sceneType": "mjcf"}
    )
    assert tool.formats == ("blend", "stl", "obj", "mjcf")
    # 'sceneType' still means something of its own -- that the application reads scenes.
    assert tool.deprecated == ("ownFormats", "meshVia", "imports")


def test_a_declaration_that_lists_formats_is_not_second_guessed_by_older_fields():
    tool = external.tool_from_declaration("x", {"formats": ["step"], "imports": [".stl"]})
    assert tool.formats == ("step",)
    assert tool.deprecated == ()


def test_formats_are_compared_however_they_are_spelled():
    tool = external.tool_from_declaration("x", {"formats": ["STEP", ".stl"]})
    assert tool.opens("/w/a.step") and tool.opens("/w/a.stp") and tool.opens("/w/a.STL")


def test_no_formats_means_whatever_it_is_handed():
    assert external.tool_from_declaration("x", {}).opens("/w/anything.xyz")


# ---------------------------------------------------------------------------
# Waiting, and not taking the application down
# ---------------------------------------------------------------------------


def test_stopping_pc_open_stops_the_waiting_and_not_the_application(monkeypatch):
    """Ctrl-C, or Cancel in an editor, must never close somebody's application on unsaved work."""
    killed = []

    class Process:
        def wait(self):
            raise KeyboardInterrupt

        def kill(self):
            killed.append(True)

        def terminate(self):
            killed.append(True)

    seen = {}

    def popen(args, **kwargs):
        seen.update(kwargs)
        return Process()

    monkeypatch.setattr(external.subprocess, "Popen", popen)
    with pytest.raises(external.ExternalToolError, match="still open"):
        external._launch(["freecad", "/w/a.step"])
    assert killed == []
    if os.name != "nt":
        # A session of its own, so a signal to `pc ide open` is not a signal to it.
        assert seen["start_new_session"] is True


def test_launching_waits_for_the_exit_code(monkeypatch):
    class Process:
        def wait(self):
            return 3

    monkeypatch.setattr(external.subprocess, "Popen", lambda args, **kwargs: Process())
    assert external._launch(["freecad"]) == 3


# --------------------------------------------------------------------------- #
# A dev container holding the host's Docker socket                             #
# --------------------------------------------------------------------------- #


# What a dev container's daemon reports is a Linux daemon's paths, and binding
# from them is POSIX-only (see 'docker_mount.backed_by'): a dev container is a
# Linux environment, whatever machine runs it.
linux_paths = pytest.mark.skipif(sys.platform == "win32", reason="a dev container's daemon paths are POSIX")


def _devcontainer(docker, tmp_path):
    """This machine's directories as a dev container has them from the host's daemon."""
    docker.sources = [(str(tmp_path), "/host/volumes/ws/_data"), ("/tmp", "/host/volumes/tmp/_data")]
    return docker


@linux_paths
def test_in_a_dev_container_the_workspace_is_bound_from_where_the_daemon_has_it(part, docker, tmp_path):
    """Bound as it is, the host's daemon would make an empty directory of that name on the host."""
    _devcontainer(docker, tmp_path)
    external.open_file(str(part), "freecad", use_docker=True, mode="mount")

    binds = docker.spec.mounts
    assert binds["/host/volumes/ws/_data"] == {"bind": str(tmp_path), "mode": "rw"}
    # Nothing is bound from a path the daemon does not have.
    assert str(tmp_path) not in binds
    assert all(source.startswith("/host/volumes/") for source in binds)


@linux_paths
def test_in_a_dev_container_the_display_is_bound_from_where_the_host_has_it(docker, tmp_path):
    """The X socket this container has from the host is the host's own display: bound from there."""
    _devcontainer(docker, tmp_path)
    docker.sources.append(("/tmp/.X11-unix", "/tmp/.X11-unix-of-the-host"))
    x11 = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
    cookie = {"/opt/nowhere/.Xauthority": {"bind": "/tmp/.partcad-xauth", "mode": "ro"}}

    _, binds = external._binds(external.TOOLS["freecad"], "img", [str(tmp_path)], {**x11, **cookie})

    assert binds["/tmp/.X11-unix-of-the-host"] == {"bind": "/tmp/.X11-unix", "mode": "rw"}
    # A file this container does not have from the host is the host's already.
    assert binds["/opt/nowhere/.Xauthority"] == {"bind": "/tmp/.partcad-xauth", "mode": "ro"}


def test_on_an_ordinary_host_everything_is_bound_as_it_is(docker, tmp_path):
    x11 = {"/tmp/.X11-unix": {"bind": "/tmp/.X11-unix", "mode": "rw"}}
    mounts, binds = external._binds(external.TOOLS["freecad"], "img", [str(tmp_path)], x11)
    assert mounts == {str(tmp_path): {"bind": str(tmp_path), "mode": "rw"}}
    assert binds == x11


def test_a_daemon_that_cannot_see_these_files_says_to_send_them(part, docker):
    docker.sources = False
    with pytest.raises(external.ExternalToolError, match="useDockerRemote"):
        external.open_file(str(part), "freecad", use_docker=True, mode="mount")
    assert docker.spec is None


@linux_paths
def test_a_directory_on_none_of_the_containers_mounts_is_named(part, docker, tmp_path):
    docker.sources = [("/somewhere/else", "/host/else")]
    with pytest.raises(external.ExternalToolError) as raised:
        external.open_file(str(part), "freecad", use_docker=True, mode="mount")
    assert str(tmp_path) in str(raised.value)
    assert "PC_DOCKER_MOUNT_SOURCES" in str(raised.value)


def test_upload_mode_does_not_ask_where_the_daemon_has_anything(part, docker):
    """Nothing is bound, so there is nothing to ask -- and a daemon elsewhere answers False."""
    docker.sources = False
    external.open_file(str(part), "freecad", use_docker=True, mode="upload")
    assert docker.spec.mounts == {}


def test_a_file_in_no_workspace_gets_its_own_directory_not_where_the_command_ran(tmp_path, docker, monkeypatch):
    """Run from '/' or '~', the "workspace" found was that, and all of it was bound in."""
    loose = tmp_path / "loose"
    loose.mkdir()
    part = loose / "cube.step"
    part.write_text("ISO-10303-21;\n")
    monkeypatch.chdir(tmp_path)  # no partcad.yaml here, and the file is under it

    external.open_file(str(part), "freecad", use_docker=True, mode="mount")

    bound = [value["bind"] for value in docker.spec.mounts.values()]
    assert str(loose) in bound
    assert str(tmp_path) not in bound


@linux_paths
def test_in_a_dev_container_a_state_directory_the_daemon_lacks_is_left_out(part, docker, tmp_path, monkeypatch):
    """It is there for the daemon's socket, which nothing in the application needs."""
    docker.sources = [(str(tmp_path), "/host/volumes/ws/_data")]
    monkeypatch.setattr(external, "_state_dir", lambda root: "/not/on/any/mount")
    external.open_file(str(part), "freecad", use_docker=True, mode="mount")
    assert list(docker.spec.mounts) == ["/host/volumes/ws/_data"]


@linux_paths
def test_but_not_when_the_file_opened_is_in_it(tmp_path, docker, monkeypatch):
    """A converted copy lives there: without it there is nothing to open."""
    state = tmp_path / "state"
    state.mkdir()
    copy = state / "cube.stl"
    copy.write_text("solid")
    docker.sources = [("/elsewhere", "/host/elsewhere")]
    monkeypatch.setattr(external, "_state_dir", lambda root: str(state))
    monkeypatch.setattr(external, "_workspace_for", lambda path: str(tmp_path / "ws"))
    with pytest.raises(external.ExternalToolError, match=re.escape(str(state))):
        external._open_in_container(
            external.TOOLS["freecad"], str(copy), str(tmp_path / "ws"), "img", lambda m: None, "mount"
        )
