#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for opening a file in a third-party application (`partcad_client.external`).

Two routes are pinned here, and the rule that decides between them: a locally
installed application is used whenever there is one, and a container is only
ever reached for when the caller has allowed it. Everything the container route
does is a `docker` command line, so that is what these tests read -- the mounts
that make the workspace and the daemon socket visible at the paths they have on
the host, the display the window comes out on, and the refusals that carry the
instructions a user has to follow.

Nothing here runs Docker, and nothing starts an application: `_run` and `_spawn`
are the two places where this module reaches out of the process, and both are
replaced.
"""

import os
import subprocess

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


@pytest.fixture
def spawned(monkeypatch):
    """Record what would have been started, instead of starting it."""
    started = []
    monkeypatch.setattr(external, "_spawn", lambda args: started.append(list(args)))
    return started


class FakeDocker:
    """A `docker` that answers from state a test sets, and records every call."""

    def __init__(self):
        self.commands = []
        # None means the container does not exist yet.
        self.state = None
        self.mounts = []
        self.available = True
        self.binaries = ["/usr/bin/freecad"]
        self.exec_returncode = 0

    def install(self, monkeypatch):
        monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        monkeypatch.setattr(external, "_run", self)
        return self

    def __call__(self, args, timeout=external.DOCKER_TIMEOUT):
        self.commands.append(list(args))
        return self._answer(list(args))

    def _answer(self, args):
        if args[:2] == ["docker", "info"]:
            return self._result(0 if self.available else 1, stderr="Cannot connect to the Docker daemon")
        if args[:2] == ["docker", "ps"]:
            if self.state is None:
                return self._result(0)
            # Whichever container was asked about: there is more than one tool.
            asked = next(value.split("=", 1)[1] for flag, value in zip(args, args[1:]) if flag == "--filter")
            return self._result(0, stdout="%s\t%s\n" % (asked, self.state))
        if args[:2] == ["docker", "run"]:
            self.state = "running"
            self.mounts = [value.split(":")[1] for flag, value in zip(args, args[1:]) if flag == "--volume"]
            return self._result(0)
        if args[:2] == ["docker", "start"]:
            self.state = "running"
            return self._result(0)
        if args[:2] == ["docker", "inspect"]:
            return self._result(0, stdout="".join(destination + "\n" for destination in self.mounts))
        if args[:2] == ["docker", "exec"]:
            if args[-2:-1] == ["-c"] or "command -v" in args[-1]:
                wanted = args[-1].rsplit(" ", 1)[-1]
                found = [b for b in self.binaries if b.rsplit("/", 1)[-1] == wanted]
                return self._result(0 if found else 1, stdout=(found[0] + "\n") if found else "")
            return self._result(self.exec_returncode, stderr="" if not self.exec_returncode else "exec failed")
        raise AssertionError("unexpected docker command: %s" % " ".join(args))

    @staticmethod
    def _result(returncode, stdout="", stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def command(self, *prefix):
        """The first recorded command starting with ``prefix``."""
        for args in self.commands:
            if args[: len(prefix)] == list(prefix):
                return args
        return None


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
    assert docker.commands == []


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


def test_the_container_is_created_with_the_workspace_and_the_socket_mounted(part, docker, workspace_socket, tmp_path):
    result = external.open_file(str(part), use_docker=True)
    assert result.method == "docker"
    created = docker.command("docker", "run")
    # Mounted at the path they have on the host, so that one path means the same
    # thing on both sides -- the file argument below is that same host path.
    assert "%s:%s" % (tmp_path, tmp_path) in created
    assert "%s:%s" % (workspace_socket, workspace_socket) in created
    assert "--name" in created and "partcad-freecad" in created


def test_the_socket_directory_is_made_so_a_later_daemon_is_visible(part, docker, monkeypatch, tmp_path):
    # The mounts are fixed when the container is created, and this container
    # outlives the daemon several times over: waiting for one to exist would
    # mean a container that can never see the one that eventually starts.
    socket_dir = tmp_path / "state" / "workspaces" / "hash"
    monkeypatch.setattr(external, "socket_path", lambda _root: str(socket_dir / "socket"))
    external.open_file(str(part), use_docker=True)
    assert socket_dir.is_dir()
    assert "%s:%s" % (socket_dir, socket_dir) in docker.command("docker", "run")


def test_the_container_is_named_after_the_tool_not_the_image(part, docker):
    external.open_file(str(part), use_docker=True)
    created = docker.command("docker", "run")
    assert created[created.index("--name") + 1] == "partcad-freecad"
    assert created[-3] == external.FREECAD.image


def test_a_custom_image_replaces_the_default_one(part, docker):
    external.open_file(str(part), use_docker=True, image="freecad/freecad:weekly")
    assert docker.command("docker", "run")[-3] == "freecad/freecad:weekly"


def test_an_existing_container_is_reused_rather_than_recreated(part, docker, tmp_path):
    docker.state = "running"
    docker.mounts = [str(tmp_path)]
    external.open_file(str(part), use_docker=True)
    assert docker.command("docker", "run") is None
    assert docker.command("docker", "start") is None


def test_a_stopped_container_is_started(part, docker, tmp_path):
    docker.state = "exited"
    docker.mounts = [str(tmp_path)]
    external.open_file(str(part), use_docker=True)
    assert docker.command("docker", "start") == ["docker", "start", "partcad-freecad"]


def test_a_container_from_another_workspace_is_refused_with_the_way_out(part, docker):
    docker.state = "running"
    docker.mounts = ["/somewhere/else"]
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "docker rm -f partcad-freecad" in str(caught.value)


def test_a_container_without_the_application_is_refused_with_the_way_out(part, docker):
    docker.binaries = []
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "docker rm -f partcad-freecad" in str(caught.value)


def test_the_application_is_started_in_the_container_on_the_host_file(part, docker):
    external.open_file(str(part), use_docker=True)
    started = docker.command("docker", "exec", "--detach")
    assert started[-2:] == ["/usr/bin/freecad", str(part)]
    assert "DISPLAY=:0" in started


def test_a_file_outside_this_workspace_still_gets_a_mount_that_holds_it(tmp_path, docker, monkeypatch):
    # Whatever is mounted has to contain the file, or the application would be
    # handed a name the container cannot resolve. The workspace `pc open` runs
    # in is preferred -- it is the one with a daemon -- but it is not imposed.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = elsewhere / "cube.step"
    outside.write_text("ISO-10303-21;\n")

    external.open_file(str(outside), use_docker=True)
    created = docker.command("docker", "run")
    assert "%s:%s" % (elsewhere, elsewhere) in created
    assert "%s:%s" % (workspace, workspace) not in created


def test_the_workspace_the_command_runs_in_is_the_one_mounted(part, docker, monkeypatch, tmp_path):
    # The file is under it, so this is the workspace whose daemon socket is
    # worth mounting beside it -- which is what an editor's `pc open` means.
    nested = tmp_path / "parts"
    nested.mkdir()
    monkeypatch.chdir(nested)
    external.open_file(str(part), use_docker=True)
    assert "%s:%s" % (tmp_path, tmp_path) in docker.command("docker", "run")


def test_a_failed_exec_is_reported_with_what_docker_said(part, docker):
    docker.exec_returncode = 1
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "exec failed" in str(caught.value)


# ---------------------------------------------------------------------------
# Getting the window onto the user's screen
# ---------------------------------------------------------------------------


def test_linux_shares_the_x_socket_and_the_display(part, docker, monkeypatch):
    # The display is a socket on this machine, so the container gets the socket
    # rather than instructions for setting up an X server.
    real_isdir = external.os.path.isdir
    monkeypatch.setattr(external.os.path, "isdir", lambda path: True if path == "/tmp/.X11-unix" else real_isdir(path))
    external.open_file(str(part), use_docker=True)
    created = docker.command("docker", "run")
    assert "/tmp/.X11-unix:/tmp/.X11-unix:rw" in created
    assert "DISPLAY=:0" in created


def test_linux_passes_the_x_cookie_as_well_as_the_socket(part, docker, monkeypatch, tmp_path):
    # The file *and* the variable naming it: an X client that cannot find the
    # cookie is refused by the server, and the container's home directory is not
    # the user's.
    cookie = tmp_path / "Xauthority"
    cookie.write_text("cookie")
    monkeypatch.setenv("XAUTHORITY", str(cookie))
    external.open_file(str(part), use_docker=True)
    created = docker.command("docker", "run")
    assert "%s:%s:ro" % (cookie, cookie) in created
    assert "XAUTHORITY=%s" % cookie in created


def test_a_forwarded_linux_display_is_reached_over_the_host_gateway(part, docker, monkeypatch):
    # An SSH-forwarded display is TCP, not a socket: there is nothing to share,
    # so the container is told where the host is instead.
    monkeypatch.setenv("DISPLAY", "localhost:10.0")
    external.open_file(str(part), use_docker=True)
    created = docker.command("docker", "run")
    assert "DISPLAY=host.docker.internal:10.0" in created
    assert "host.docker.internal:host-gateway" in created


def test_linux_without_a_display_says_so_before_creating_anything(part, docker, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "DISPLAY" in str(caught.value)
    assert docker.command("docker", "run") is None


def test_macos_without_an_x_server_names_the_one_to_install(part, docker, monkeypatch):
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(external, "_xquartz_installed", lambda: False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "XQuartz" in str(caught.value)
    assert docker.command("docker", "run") is None


def test_macos_reaches_the_host_x_server_over_tcp(part, docker, monkeypatch):
    # The launchd socket macOS puts in DISPLAY means nothing inside a container.
    monkeypatch.setattr(external.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("DISPLAY", "/private/tmp/com.apple.launchd.7Uu/org.xquartz:0")
    monkeypatch.setattr(external, "_xquartz_installed", lambda: True)
    result = external.open_file(str(part), use_docker=True)
    assert "DISPLAY=host.docker.internal:0" in docker.command("docker", "run")
    assert "xhost" in result.detail


def test_windows_without_a_display_names_the_x_servers_to_install(part, docker, monkeypatch):
    monkeypatch.setattr(external.platform, "system", lambda: "Windows")
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(external.ExternalToolError) as caught:
        external.open_file(str(part), use_docker=True)
    assert "VcXsrv" in str(caught.value)
    assert docker.command("docker", "run") is None


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


def test_every_tool_can_be_named_and_has_a_container_of_its_own():
    assert external.tool_names() == ["freecad", "gazebo", "kicad"]
    names = {external.TOOLS[name].container_name for name in external.tool_names()}
    assert names == {"partcad-freecad", "partcad-gazebo", "partcad-kicad"}


def test_the_kicad_container_is_the_image_partcad_already_builds():
    """One KiCad container in the product, not two.

    'partcad.part_factory_kicad' pulls the same image, pinned to the same
    release, to run 'kicad-cli' in. Pinning matters here as much as it does
    there: the container carries PartCAD's own environment.
    """
    from partcad_client import __version__

    assert external.TOOLS["kicad"].image == "ghcr.io/partcad/partcad-container-kicad:" + __version__


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
def test_each_generation_of_gazebo_is_launched_the_way_it_wants(monkeypatch, spawned, world, binary, expected):
    """`gz sim`, `ign gazebo` and plain `gazebo` are one application, three front ends."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/" + name if name == binary else None)

    result = external.open_file(str(world), tool="gazebo")

    assert result.method == "native"
    assert spawned == [["/usr/bin/" + binary] + expected + [str(world)]]


def test_gazebo_runs_in_its_own_container_with_the_world_file(world, docker):
    docker.binaries = ["/usr/bin/gz"]

    result = external.open_file(str(world), tool="gazebo", use_docker=True)

    assert result.method == "docker"
    created = docker.command("docker", "run")
    assert "partcad-gazebo" in created
    assert external.TOOLS["gazebo"].image in created
    # The arguments the executable found *inside* the container needs, not the
    # ones the host would have needed.
    assert docker.command("docker", "exec", "--detach")[-3:] == ["/usr/bin/gz", "sim", str(world)]


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


def test_a_step_with_no_board_beside_it_is_handed_over_as_it_is(monkeypatch, spawned, part):
    """Nothing is created and nothing is converted: `pc open` renders nothing."""
    monkeypatch.setattr(external.shutil, "which", lambda name: "/usr/bin/kicad" if name == "kicad" else None)

    external.open_file(str(part), tool="kicad")

    assert spawned == [["/usr/bin/kicad", str(part)]]


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
    gazebo = external.TOOLS["gazebo"]

    # The Windows form is spelled with the separator this platform uses, since
    # that is what `native_command()` builds it with there.
    assert gazebo.launch_args("/usr/bin/gz") == ("sim",)
    assert gazebo.launch_args(os.path.join("Gazebo", "bin", "gz.exe")) == ("sim",)
    assert gazebo.launch_args("org.gazebosim.Gazebo") == ()
    assert gazebo.launch_args("/Applications/Gazebo.app") == ()
