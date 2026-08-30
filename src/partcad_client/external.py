#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Opening a file in a third-party application, on the machine the client runs on.

This is a client's job by construction, and it is why the code sits here rather
than behind an RPC method. A daemon can be remote: "open this in FreeCAD" sent to
one would start a window on somebody else's desk, on a machine that may have no
display at all -- and the file named on the command line is the client's own,
found by a path that means nothing on the other side of the wire. So `pc open`
never speaks to a daemon, the way `pc lint --file` and `pc upgrade` do not, and
the VS Code extension reaches this code by running `pc open` rather than by
reimplementing it in TypeScript.

Two ways to run a tool, tried in this order:

* **Natively**, when the machine has the application installed. Nothing is
  containerised, nothing is downloaded, and the application sees the file at the
  path the user typed.
* **In a container**, when it does not, Docker is available, and the caller
  passed ``use_docker``. One long-lived container per tool, named
  ``partcad-<tool>`` -- a *container* name, not an image name, so a user can
  create, inspect, customise or `docker rm` theirs, and the next `pc open` finds
  and reuses whatever is there.

The container mounts the workspace root **at the same absolute path** it has on
the host, along with the directory holding the workspace's daemon socket. Same
path on both sides is what keeps the arrangement honest: the file argument, an
error message, and anything the application writes back all name one path that
means the same thing inside the container, on the host, and to the daemon.

A containerised GUI needs an X server on the host, which is the one place where
this cannot paper over the difference between platforms. On Linux the display is
usually a socket that can simply be shared, cookie and all, and nothing has to be
set up; on macOS and Windows -- and on Linux over a forwarded display -- it is a
TCP connection to an X server the user has to install and allow. There is no way
to do that for them, so when it is missing they get told which one to install and
what to run, rather than a container that starts and silently never shows a window.
"""

import contextlib
import glob
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from partcad_utils.workspace import determine_root_path, socket_path

from . import __version__

__all__ = [
    "ExternalToolError",
    "OpenResult",
    "Tool",
    "TOOLS",
    "open_file",
    "tool_names",
]

# How long to wait for the `docker` commands that only ask a question. Generous
# enough for a busy daemon, short enough that a wedged one is reported rather
# than hanging an editor's context menu.
DOCKER_TIMEOUT = 60.0

# The container's name is derived from the tool's, so `pc open --with freecad`
# uses `partcad-freecad`. Deliberately a fixed name rather than a fresh
# container each time: the user can prepare theirs (install add-ons, keep
# preferences) and PartCAD will keep using it.
CONTAINER_PREFIX = "partcad-"


class ExternalToolError(Exception):
    """No way to open the file, with a message saying what would fix that."""


@dataclass(frozen=True)
class Tool:
    """A third-party application PartCAD knows how to launch.

    Everything platform-specific about finding one is data, so that adding the
    second tool is a table entry rather than another copy of the logic below.
    """

    name: str
    display_name: str
    # The image a container is created from when the machine has no local copy.
    image: str
    # Executable names to look for, both on this machine's PATH and inside the
    # container. Ordered: the first one found wins.
    binaries: Tuple[str, ...] = ()
    # macOS application bundles, looked for under /Applications and ~/Applications.
    macos_apps: Tuple[str, ...] = ()
    # Windows install locations, as globs relative to the directories in
    # `windows_roots`, so a versioned directory name still matches.
    windows_globs: Tuple[str, ...] = ()
    flatpak_id: Optional[str] = None
    # Extra arguments the application needs before the file name, if any.
    args: Tuple[str, ...] = field(default_factory=tuple)
    # The same, for one executable in particular. An application with more than
    # one front end needs it: Gazebo's world file is `gz sim <world>` through
    # the current command and a bare `gazebo <world>` through the old one, and
    # which of the two is on the machine decides.
    binary_args: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    # Extensions this application actually opens, when the file it is handed is
    # not one of them and one of these sits beside it. A PartCAD `kicad` part
    # *is* the STEP file KiCad's CLI writes out of the board; the board itself --
    # what somebody opening KiCad means -- is the project file next to it, and
    # the tree has no other name for it.
    companions: Tuple[str, ...] = ()

    @property
    def container_name(self) -> str:
        return CONTAINER_PREFIX + self.name

    def launch_args(self, executable: str) -> Tuple[str, ...]:
        """The arguments that go before the file name for this executable.

        Keyed on the name of the program itself, so it answers for a binary
        found on the PATH, in a container, or under a Windows install alike. A
        launcher that is not the program -- macOS's `open -a`, `flatpak run` --
        has no entry and gets `args`, which is right: each of those bundles one
        front end and knows which of its own arguments to supply.
        """
        stem = os.path.splitext(os.path.basename(executable))[0]
        return self.binary_args.get(stem, self.args)

    def file_for(self, path: str) -> str:
        """The file this application is really given, from the one it was handed.

        Unchanged unless the tool declares `companions` and the path is not one
        of them: then the first companion that exists beside it wins. Nothing is
        created and nothing is converted -- `pc open` renders nothing -- so a
        file with no companion is handed over as it is and the application says
        what it thinks of it.
        """
        if not self.companions:
            return path
        stem, extension = os.path.splitext(path)
        if extension.lower() in self.companions:
            return path
        for companion in self.companions:
            candidate = stem + companion
            if os.path.isfile(candidate):
                return candidate
        return path


FREECAD = Tool(
    name="freecad",
    display_name="FreeCAD",
    # `:latest`, not a pinned tag: a user asking for a container wants the
    # current FreeCAD, and a pin here would quietly age into a version nobody
    # chose. The image is a community one because the FreeCAD project publishes
    # none -- the `freecad/freecad` repository on Docker Hub has never had an
    # image pushed to it -- and it is this one because it carries a GUI FreeCAD
    # on `PATH` and is still being rebuilt. `--docker-image` overrides it, which
    # is also the answer for anyone who would rather run their own.
    image="linuxserver/freecad:latest",
    binaries=("freecad", "FreeCAD", "freecad-daily"),
    macos_apps=("FreeCAD.app",),
    windows_globs=("FreeCAD*/bin/FreeCAD.exe", "FreeCAD*/FreeCAD.exe"),
    flatpak_id="org.freecad.FreeCAD",
)

GAZEBO = Tool(
    name="gazebo",
    display_name="Gazebo",
    # The simulator's own image for the current Gazebo. `:latest`, for the
    # reason FreeCAD's is: a user asking for a container wants the current
    # Gazebo, and `--docker-image` is the answer for anyone who wants another
    # one (`osrf/gazebo` for Gazebo Classic, say).
    image="gazebosim/gz-harmonic:latest",
    # Three generations of one program, newest first: `gz sim` today, `ign
    # gazebo` in the Ignition years, and `gazebo` for Gazebo Classic. Whichever
    # the machine has is the one used.
    binaries=("gz", "ign", "gazebo"),
    binary_args={"gz": ("sim",), "ign": ("gazebo",)},
    macos_apps=("Gazebo.app",),
    windows_globs=("Gazebo*/bin/gz.exe",),
    flatpak_id="org.gazebosim.Gazebo",
)

KICAD = Tool(
    name="kicad",
    display_name="KiCad",
    # The image PartCAD already builds and uses for `kicad` parts (see
    # 'partcad.part_factory_kicad'), pinned to this release the same way: it is
    # `kicad/kicad` with PartCAD's own environment on top, so the GUI is in it
    # and there is one KiCad container in the product rather than two. It is
    # `linux/amd64` only, as KiCad's own images are; a machine that cannot run
    # it almost certainly has KiCad installed, which is used first anyway.
    image="ghcr.io/partcad/partcad-container-kicad:" + __version__,
    binaries=("kicad",),
    macos_apps=("KiCad/KiCad.app", "KiCad.app"),
    windows_globs=("KiCad/*/bin/kicad.exe",),
    flatpak_id="org.kicad.KiCad",
    # What a `kicad` part points at is the STEP file KiCad's CLI generates from
    # the board. The board is the project beside it, and that is what opening
    # KiCad means.
    companions=(".kicad_pro", ".kicad_pcb", ".kicad_sch"),
)

# The tools `pc open --with` accepts. Each is a row here, not a branch anywhere
# below.
TOOLS: Dict[str, Tool] = {tool.name: tool for tool in (FREECAD, GAZEBO, KICAD)}


def tool_names() -> List[str]:
    """The tools that can be named, in the order they are offered."""
    return list(TOOLS)


@dataclass
class OpenResult:
    """What was opened, and how -- so a caller can say so rather than guess."""

    tool: str
    # "native" or "docker": which of the two routes below actually ran.
    method: str
    path: str
    command: List[str]
    detail: str

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "tool": self.tool,
            "method": self.method,
            "path": self.path,
            "command": list(self.command),
            "detail": self.detail,
        }


def open_file(
    path: str,
    tool: str = FREECAD.name,
    use_docker: bool = False,
    image: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> OpenResult:
    """Open ``path`` in ``tool``, natively if it is installed, else in a container.

    ``use_docker`` is the caller's permission to fall back to a container, not a
    demand for one: a machine with the application installed uses it either way.
    Without that permission, and without a local installation, this raises rather
    than pulling an image nobody asked for.
    """
    say = log or (lambda _message: None)

    spec = TOOLS.get(tool)
    if spec is None:
        raise ExternalToolError(
            "Unknown application '%s'. PartCAD can open files in: %s." % (tool, ", ".join(tool_names()))
        )

    resolved = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(resolved):
        raise ExternalToolError("No such file: %s" % resolved)
    resolved = spec.file_for(resolved)

    native = native_command(spec)
    if native is not None:
        command = list(native) + list(spec.launch_args(native[-1])) + [resolved]
        say("Opening %s in %s..." % (resolved, spec.display_name))
        _spawn(command)
        return OpenResult(
            tool=spec.name,
            method="native",
            path=resolved,
            command=command,
            detail="%s is installed on this machine." % spec.display_name,
        )

    if not use_docker:
        raise ExternalToolError(
            "%s was not found on this machine.\n"
            "Install it, or let PartCAD run it in a container: pass --use-docker to `pc open` "
            "(the 'partcad.open.useDocker' setting in the VS Code extension)." % spec.display_name
        )

    return _open_in_container(spec, resolved, image, say)


# ---------------------------------------------------------------------------
# A local installation
# ---------------------------------------------------------------------------


def native_command(spec: Tool) -> Optional[List[str]]:
    """The command that runs a locally installed ``spec``, or None if there is none.

    Every platform's usual answers, in the order a user would expect them: what
    is on the PATH first, because that is what they chose to put there, then the
    places an installer puts things.
    """
    for binary in spec.binaries:
        found = shutil.which(binary)
        if found:
            return [found]

    system = platform.system()
    if system == "Darwin":
        for app in spec.macos_apps:
            for directory in ("/Applications", os.path.expanduser("~/Applications")):
                bundle = os.path.join(directory, app)
                if os.path.isdir(bundle):
                    # Through `open`, not the executable inside the bundle: it is
                    # how macOS launches an application, and it reuses a running
                    # instance instead of starting a second one.
                    return ["open", "-a", bundle]
    elif system == "Windows":  # pragma: no cover - exercised only on Windows
        for root in _windows_roots():
            for pattern in spec.windows_globs:
                matches = sorted(glob.glob(os.path.join(root, pattern.replace("/", os.sep))))
                if matches:
                    # Newest-looking last, so a machine with two versions gets
                    # the later one.
                    return [matches[-1]]
    elif spec.flatpak_id is not None and shutil.which("flatpak"):
        # Asked only once nothing else has matched: it costs a process, and a
        # flatpak is rarely the only copy on a machine that has one.
        if _run(["flatpak", "info", spec.flatpak_id]).returncode == 0:
            return ["flatpak", "run", spec.flatpak_id]

    return None


def _windows_roots() -> List[str]:  # pragma: no cover - exercised only on Windows
    """The directories Windows installers put applications in."""
    roots = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            roots.append(value)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Programs"))
    return roots


# ---------------------------------------------------------------------------
# A container
# ---------------------------------------------------------------------------


def _open_in_container(spec: Tool, path: str, image: Optional[str], say: Callable[[str], None]) -> OpenResult:
    """Run ``spec`` in its container, creating and starting one as needed."""
    if not _docker_available():
        raise ExternalToolError(
            "%s is not installed on this machine and Docker is not available to run it in a container.\n"
            "Install %s, or install Docker and make sure `docker info` succeeds."
            % (spec.display_name, spec.display_name)
        )

    # Worked out before anything is created or started: a container that cannot
    # show a window is not worth starting, and the message below is the whole
    # point of the check.
    x11_env, x11_mounts, x11_advice = _x11_forwarding(spec)
    display = x11_env["DISPLAY"]

    root = _workspace_for(path)

    state = _container_state(spec.container_name)
    if state is None:
        say("Creating the '%s' container from %s..." % (spec.container_name, image or spec.image))
        _create_container(spec, image or spec.image, root, x11_mounts, x11_env)
    else:
        _check_container_mounts(spec, root)
        if state != "running":
            say("Starting the '%s' container..." % spec.container_name)
            _start_container(spec.container_name)

    binary = _container_binary(spec)
    # The display travels on the exec rather than being left to what the
    # container was created with: the container outlives the session, and the
    # display the user is on now is the one the window has to come out on.
    command = [
        "docker",
        "exec",
        "--detach",
        *_env_args(x11_env),
        "--workdir",
        root,
        spec.container_name,
        binary,
        *spec.launch_args(binary),
        path,
    ]
    say("Opening %s in %s (container '%s', DISPLAY=%s)..." % (path, spec.display_name, spec.container_name, display))
    result = _run(command)
    if result.returncode != 0:
        raise ExternalToolError(
            "Failed to start %s in the '%s' container: %s"
            % (spec.display_name, spec.container_name, _message(result) or "docker exec failed")
        )

    detail = "%s runs in the '%s' container, displaying on %s." % (spec.display_name, spec.container_name, display)
    if x11_advice:
        detail += "\n" + x11_advice
    return OpenResult(tool=spec.name, method="docker", path=path, command=command, detail=detail)


def _env_args(env: Dict[str, str]) -> List[str]:
    """``--env K=V`` for each entry, in a fixed order so a command line is stable."""
    args = []
    for key in sorted(env):
        args += ["--env", "%s=%s" % (key, env[key])]
    return args


def _workspace_for(path: str) -> str:
    """The workspace to mount into the container so that ``path`` is inside it.

    The one this command runs in, when it holds the file: that is the workspace
    whose daemon socket is worth mounting beside it, and the one the caller
    means -- an editor runs `pc open` in the window's workspace folder. A file
    somewhere else gets its own workspace mounted instead, which still contains
    it; there is simply no daemon of this workspace's to offer it.
    """
    root = determine_root_path()
    if _is_within(path, root):
        return root
    return determine_root_path(os.path.dirname(path))


def _docker_available() -> bool:
    """True when there is a `docker` that answers -- not merely one on the PATH.

    A CLI with no daemon behind it is the common case (Docker Desktop not
    started), and it fails several seconds later inside `docker run`, where the
    error says nothing useful.
    """
    if shutil.which("docker") is None:
        return False
    return _run(["docker", "info"]).returncode == 0


def _container_state(name: str) -> Optional[str]:
    """The state of the container named ``name`` ("running", "exited", ...), or None.

    The filter narrows the listing; the name is then compared exactly, because
    `--filter name=` is a substring pattern -- a user's `partcad-freecad-test`
    must not be mistaken for the container PartCAD manages.
    """
    result = _run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            "name=" + name,
            "--format",
            "{{.Names}}\t{{.State}}",
        ]
    )
    if result.returncode != 0:
        raise ExternalToolError("Failed to look for the '%s' container: %s" % (name, _message(result)))
    for line in (result.stdout or "").splitlines():
        fields = line.strip().split("\t")
        if len(fields) == 2 and fields[0] == name:
            return fields[1]
    return None


def _create_container(spec: Tool, image: str, root: str, x11_mounts: List[str], x11_env: Dict[str, str]) -> None:
    """Create the tool's container, mounting the workspace and the daemon socket.

    The container is created idle (it sleeps) and the application is started in
    it with `docker exec`, rather than being the container's own command. One
    container then serves every `pc open`: the first one does not have to be
    treated differently from the next, and closing the application's window does
    not throw away a container the user may have customised.
    """
    mounts = ["--volume", "%s:%s" % (root, root)]

    # The daemon's socket, so that a PartCAD running inside the container talks
    # to the same daemon this workspace already has, instead of starting a
    # second one against a directory only it can see. The directory is mounted
    # rather than the socket file: a restarted daemon creates a new socket, and
    # a bind mount of the old file would keep pointing at something that is gone.
    #
    # Created here if it does not exist yet, because the mounts are fixed when
    # the container is created and this container outlives the daemon several
    # times over. Waiting for a daemon that has not started would mean a
    # container that can never see the one that eventually does -- and the
    # directory is PartCAD's own, which the daemon would create the same way.
    socket_dir = os.path.dirname(socket_path(root))
    with contextlib.suppress(OSError):
        os.makedirs(socket_dir, exist_ok=True)
    if os.path.isdir(socket_dir):
        mounts += ["--volume", "%s:%s" % (socket_dir, socket_dir)]

    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        spec.container_name,
        "--workdir",
        root,
        *_env_args(x11_env),
        *mounts,
        *x11_mounts,
        # The image's own entrypoint is the application; it has to be replaced
        # for the container to stay up and wait for `docker exec`.
        "--entrypoint",
        "sh",
        image,
        "-c",
        "while true; do sleep 3600; done",
    ]
    result = _run(command, timeout=None)
    if result.returncode != 0:
        raise ExternalToolError(
            "Failed to create the '%s' container from %s: %s" % (spec.container_name, image, _message(result))
        )


def _start_container(name: str) -> None:
    result = _run(["docker", "start", name])
    if result.returncode != 0:
        raise ExternalToolError("Failed to start the '%s' container: %s" % (name, _message(result)))


def _check_container_mounts(spec: Tool, root: str) -> None:
    """Refuse an existing container that cannot see this workspace.

    A container outlives the workspace it was created for, and the mounts are
    fixed when it is created. Without this check the application starts, reports
    that the file does not exist, and the user has no way to know why.
    """
    result = _run(
        ["docker", "inspect", "--format", "{{range .Mounts}}{{println .Destination}}{{end}}", spec.container_name]
    )
    if result.returncode != 0:
        # Not fatal: an old Docker that formats this differently must not stop
        # a container that is very probably fine.
        return
    mounted = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not mounted:
        return
    if any(_is_within(root, destination) for destination in mounted):
        return
    raise ExternalToolError(
        "The '%s' container does not have this workspace (%s) mounted; it was created for a different one.\n"
        "Remove it and PartCAD will create one for this workspace: docker rm -f %s"
        % (spec.container_name, root, spec.container_name)
    )


def _container_binary(spec: Tool) -> str:
    """The application's executable inside the container, or an error naming why not."""
    for binary in spec.binaries:
        result = _run(["docker", "exec", spec.container_name, "sh", "-c", "command -v " + binary])
        if result.returncode == 0 and (result.stdout or "").strip():
            return (result.stdout or "").strip().splitlines()[0]
    raise ExternalToolError(
        "The '%s' container has no %s executable (looked for: %s).\n"
        "Remove it so that PartCAD recreates it from %s: docker rm -f %s"
        % (
            spec.container_name,
            spec.display_name,
            ", ".join(spec.binaries),
            spec.image,
            spec.container_name,
        )
    )


# ---------------------------------------------------------------------------
# Getting the window onto the user's screen
# ---------------------------------------------------------------------------

_LINUX_NO_DISPLAY = (
    "There is no X display to show {name} on (DISPLAY is not set).\n"
    "Run `pc open` from a graphical session, or set DISPLAY to the X server to use.\n"
    "Under Wayland, install XWayland so that X applications have a display."
)

_MACOS_NO_DISPLAY = (
    "Running {name} in a container needs an X server on macOS, and none was found.\n"
    "Install XQuartz (https://www.xquartz.org/ or `brew install --cask xquartz`), then:\n"
    "  1. start XQuartz and turn on Preferences > Security > 'Allow connections from network clients';\n"
    "  2. log out and back in, so XQuartz restarts with that setting;\n"
    "  3. run `xhost + 127.0.0.1` to let the container connect.\n"
    "Install {name} on this machine instead if you would rather not run an X server."
)

_WINDOWS_NO_DISPLAY = (
    "Running {name} in a container needs an X server on Windows, and none was found.\n"
    "Install one -- VcXsrv (https://sourceforge.net/projects/vcxsrv/), X410 or Xming -- start it with\n"
    "access control disabled ('Disable access control' in the VcXsrv wizard), then set DISPLAY, e.g.\n"
    "  set DISPLAY=host.docker.internal:0\n"
    "Install {name} on this machine instead if you would rather not run an X server."
)

_MACOS_ADVICE = "If no window appears, run `xhost + 127.0.0.1` in a terminal and check that XQuartz is running."
_WINDOWS_ADVICE = "If no window appears, check that the X server is running with access control disabled."
_LINUX_ADVICE = "If the application reports 'Authorization required', run `xhost +local:` to let the container connect."
_LINUX_TCP_ADVICE = (
    "The display is reached over TCP, so the container connects to it as host.docker.internal; "
    "run `xhost +` on the machine running the X server if it is refused."
)


def _x11_forwarding(spec: Tool) -> Tuple[Dict[str, str], List[str], str]:
    """How the container reaches the user's screen: (environment, mounts, advice).

    Raises with instructions when there is nothing to reach. That message is the
    reason this runs before the container is created: an unusable container that
    starts and shows nothing is worse than a command that says what to install.
    """
    system = platform.system()
    display = os.environ.get("DISPLAY", "").strip()

    if system == "Darwin":
        if not (display or _xquartz_installed()):
            raise ExternalToolError(_MACOS_NO_DISPLAY.format(name=spec.display_name))
        # Always over TCP: the container has no access to the launchd socket
        # macOS puts in DISPLAY, and host.docker.internal is how Docker Desktop
        # exposes the host to it.
        return {"DISPLAY": _host_display(display)}, [], _MACOS_ADVICE

    if system == "Windows":  # pragma: no cover - exercised only on Windows
        if not display:
            raise ExternalToolError(_WINDOWS_NO_DISPLAY.format(name=spec.display_name))
        return {"DISPLAY": _host_display(display)}, [], _WINDOWS_ADVICE

    if not display:
        raise ExternalToolError(_LINUX_NO_DISPLAY.format(name=spec.display_name))

    host = display.rsplit(":", 1)[0] if ":" in display else ""
    if host not in ("", "unix") and not host.startswith("/"):
        # A display reached over TCP -- an SSH-forwarded one, or an X server on
        # another machine. There is no socket to share, so the container is
        # given the address instead; `host-gateway` is what makes "the host"
        # resolvable from inside a container on Linux.
        return (
            {"DISPLAY": _host_display(display)},
            ["--add-host", "host.docker.internal:host-gateway"],
            _LINUX_TCP_ADVICE,
        )

    env = {"DISPLAY": display}
    mounts = []
    if os.path.isdir("/tmp/.X11-unix"):
        # The display is a socket on this machine, so it can simply be shared --
        # no TCP, no listening X server, nothing for the user to configure.
        mounts += ["--volume", "/tmp/.X11-unix:/tmp/.X11-unix:rw"]
    xauthority = os.environ.get("XAUTHORITY")
    if xauthority and os.path.isfile(xauthority):
        # Both the file and the variable naming it: an X client that cannot find
        # the cookie is refused by the server, and the container's idea of a home
        # directory is not the user's.
        mounts += ["--volume", "%s:%s:ro" % (xauthority, xauthority)]
        env["XAUTHORITY"] = xauthority
    return env, mounts, _LINUX_ADVICE


def _xquartz_installed() -> bool:
    """True when macOS has an X server installed, even if it is not running."""
    return any(
        os.path.exists(candidate)
        for candidate in ("/Applications/Utilities/XQuartz.app", "/opt/X11/bin/Xquartz", "/opt/X11/bin/xquartz")
    )


def _host_display(display: str) -> str:
    """The host's display, addressed the way a container has to address it.

    A local display is on the host, which a container on macOS or Windows
    reaches as `host.docker.internal`. Local covers more than ":0": macOS puts
    the path of XQuartz's launchd socket in DISPLAY, which names nothing at all
    outside this machine. Anything that does name a machine is passed through
    untouched.
    """
    screen = display.rsplit(":", 1)[-1] if ":" in display else "0"
    host = display.rsplit(":", 1)[0] if ":" in display else ""
    if host in ("", "localhost", "127.0.0.1", "unix") or host.startswith("/"):
        return "host.docker.internal:" + screen
    return display


# ---------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------


def _is_within(path: str, directory: str) -> bool:
    """True when ``path`` is ``directory`` or below it."""
    try:
        relative = os.path.relpath(os.path.realpath(path), os.path.realpath(directory))
    except ValueError:  # pragma: no cover - different drives on Windows
        return False
    if relative == os.curdir:
        return True
    return relative != os.pardir and not relative.startswith(os.pardir + os.sep)


def _message(result: subprocess.CompletedProcess) -> str:
    """The most useful line Docker printed, for a message a user has to act on."""
    for stream in (result.stderr, result.stdout):
        text = (stream or "").strip()
        if text:
            return text.splitlines()[-1]
    return ""


def _run(args: List[str], timeout: Optional[float] = DOCKER_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command and capture what it said; a timeout is a failed command."""
    try:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timed out after %s seconds" % timeout)
    except OSError as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _spawn(args: List[str]) -> None:
    """Start a GUI application and leave it running once this process exits.

    Detached on purpose: `pc open` is done the moment the window belongs to the
    user, and an editor's context menu must not stay busy for as long as the
    application is open.
    """
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(args, **kwargs)
    except OSError as e:
        raise ExternalToolError("Failed to run %s: %s" % (" ".join(args), e))
