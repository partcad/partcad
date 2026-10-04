#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A sandbox whose interpreter lives in a container and whose files do not.

This is the ``venv`` sandbox with the interpreter somewhere else. The virtual
environment is still created, still installed into by pip, and still locked and
guarded by the machinery in ``runtime_python`` -- it simply lives in a directory
the container has mounted, and every command that touches it runs over there.

Which is the whole reason for mounting rather than copying. Because the sandbox
directory is at the same path on both sides (see ``docker_mount``), a virtual
environment built inside the container is a virtual environment the host can
read, ``pip`` installs survive the container being replaced, and the environment
lock, the install guards and the cache go on working without knowing that any of
this happened. A design that shipped files into the image instead would need a
second copy of all of it.

What the container buys over ``venv`` is that the interpreter, the compilers and
the native libraries come from an image somebody built once, rather than from
whatever the host happens to have -- and that a package needing something pip
cannot install can name an image carrying it. What it costs is a container
runtime.

The one thing that does **not** go through the container's RPC service is this.
``PC_CONTAINER_ALLOWED_COMMANDS`` exists because that service takes commands
from a caller who may be somewhere else and may not be trusted; ``docker exec``
here is PartCAD running a command on its own machine, in a container it started
itself, against files it already has. There is no boundary to enforce, and
pretending otherwise would mean routing pip through an allowlist that PartCAD
writes and PartCAD checks.
"""

import hashlib
import os
import platform
import re
import socket
import tempfile
import threading
import time
from typing import Optional

import docker

from partcad_utils import container_image

from . import docker_image, docker_mount
from . import logging as pc_logging
from . import runtime, runtime_python, telemetry

# The images PartCAD publishes to run its own sandboxes in, one per supported
# Python version and architecture. The tag is completed by the release and the
# version; the architecture is appended by 'docker_image.candidates()' like it
# is for anybody else's image.
BASE_IMAGE = "ghcr.io/partcad/partcad-container-python"

# What to run inside a base image to get an interpreter. Not the entry in
# 'PC_CONTAINER_ALLOWED_COMMANDS': that allowlist belongs to the RPC service,
# which this sandbox does not use. A name rather than a path, so an image is
# free to put its interpreter wherever it likes as long as it is on PATH.
CONTAINER_PYTHON = "python3"

# What keeps a sandbox container alive between commands. Its own entrypoint
# serves the RPC service, which this sandbox has no use for, so it is replaced
# with something that does nothing and stays running to be 'docker exec'd into.
KEEPALIVE = ["sleep", "infinity"]

# One thread at a time may decide what the container of a given name should be,
# because that decision can end in removing it and creating another under the
# same name. Two threads reaching it together is one of them removing the
# container the other just made -- and, since Docker answers the second removal
# of one container with a 409, a command that fails with "removal of container
# ... is already in progress" rather than running.
#
# Per name, not one lock for everything: two sandboxes for two different images
# have nothing to say to each other and should not wait on each other's pulls.
_START_LOCKS = {}
_START_LOCKS_GUARD = threading.Lock()

# How many times '_start' will go round when another *process* on this machine
# is doing the same thing at the same instant -- which the lock above cannot
# help with. Each turn is one lost race: a container removed from under the
# create, or created under the name between the look-up and the create. A
# machine losing three in a row has something wrong with it that a fourth turn
# would not fix.
_START_ATTEMPTS = 3
_START_RETRY_DELAY = 0.5


def _start_lock(name: str) -> threading.Lock:
    """The lock guarding the container called ``name``."""
    with _START_LOCKS_GUARD:
        return _START_LOCKS.setdefault(name, threading.Lock())


# Where PartCAD's own files are, on the host. The sandbox interpreter is handed
# the wrappers by path -- 'wrapper.get()' -- and the packages PartCAD ships
# inside itself the same way ('output.BUILTIN_ROOT_PATH'), and both resolve
# under this one directory, so the container has to be able to open it.
#
# Neither of the other two mounts covers it. A checkout whose virtual
# environment sits inside the package being worked on gets it for free, under
# the context root, which is what hid this for as long as it was hidden; an
# installation anywhere else is outside both, and the frozen bundle -- whose
# files are next to the executable and nowhere near either -- is outside both
# always. That is what CI caught: a bundle rendering through the 'docker'
# sandbox died on "can't open file
# '.../_internal/partcad/wrappers/wrapper_plugin.py'".
#
# Mounted rather than baked into the images PartCAD publishes, which would cost
# nothing to reach and would be wrong for a reason that is not about PartCAD's
# own images at all -- see "Why the wrappers are mounted and not baked in" in
# 'tools/containers/README.md'.
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))


def image_for(version: str, release: Optional[str] = None) -> str:
    """PartCAD's own base image for this Python version.

    The release names the tag, except where CI says otherwise -- a run building
    the images out of this commit rather than pulling the release's addresses
    them by a tag of its own. See 'partcad_utils.container_image'.
    """
    if release is None:
        from . import __version__

        release = __version__
    return "%s:%s-py%s" % (
        container_image.image_name(BASE_IMAGE),
        container_image.image_tag(release),
        version,
    )


def _short(image: str) -> str:
    """A stable short name for an image, for use in a directory or container name.

    The image name itself is full of characters neither can hold, and truncating
    it would collide between two tags of one repository -- which are exactly the
    two images most likely to be in use at once.
    """
    return hashlib.sha256(image.encode()).hexdigest()[:12]


def resolve_image(client, image: str, version: str = "") -> str:
    """The image to run, pulled if this machine does not have it yet.

    Architecture first, bare name second (see 'docker_image.candidates'). A name
    that is present locally is used without asking a registry, so an image
    somebody built by hand for testing is picked up the way a pulled one is.
    """
    names = docker_image.candidates(image)
    for name in names:
        try:
            client.images.get(name)
            return name
        except docker.errors.ImageNotFound:
            pass
    errors = []
    for name in names:
        try:
            with pc_logging.Action("Pull", version or "sandbox", name):
                client.images.pull(name)
            return name
        except Exception as e:
            errors.append("%s: %s" % (name, e))
    raise runtime.SandboxUnavailable(
        "None of the images this sandbox could run in are available: %s. "
        "Publish an architecture-suffixed tag, or check that the name is right and that this "
        "machine may pull from that registry." % "; ".join(errors)
    )


# Why an image could not be used, by image name, for whoever has to explain the
# fallback that followed. 'image_available' answers a yes/no question and the
# answer is acted on silently, which is right for the decision and useless for
# the person whose analysis then fails somewhere the image would have worked.
_UNAVAILABLE_REASONS = {}


def unavailable_reason(image: str) -> Optional[str]:
    """Why 'image_available' last said no to ``image``; ``None`` if it has not."""
    return _UNAVAILABLE_REASONS.get(image)


# How the daemon reaches this machine's directories, by the image 'image_available'
# asked about (see 'mount_sources'), for 'misses' to check a context's against.
_SOURCES = {}


def misses(image: str, needed) -> bool:
    """Whether the daemon cannot bind one of ``needed`` for ``image``; records why, as 'image_available' does.

    Separate from 'image_available' because the directories are a context's
    and the answer to that question is not: asked after it said yes.
    """
    missing = unbacked(needed, _SOURCES.get(image))
    if missing:
        _UNAVAILABLE_REASONS[image] = (
            "the Docker daemon does not share this filesystem, and %s %s not on any of the mounts it could "
            "bind from instead" % (", ".join(missing), "is" if len(missing) == 1 else "are")
        )
    return bool(missing)


def image_available(image: str, version: str = "", needed=()) -> bool:
    """Whether this machine can get an image to run that sandbox in.

    Local first, then a pull, exactly as starting the sandbox would -- so a
    False here is a failure that would have happened later, asked early enough
    that something can be done about it.

    A container runtime answering says a container *could* be started. It says
    nothing about whether the image to start is reachable, and those are
    different questions on a machine that is offline, behind a firewall, or
    simply not permitted to pull from the registry PartCAD publishes to.
    """
    if not runtime.docker_available():
        _UNAVAILABLE_REASONS[image] = "no container runtime is answering here"
        return False
    try:
        client = docker.from_env()
    except Exception as e:
        _UNAVAILABLE_REASONS[image] = "the Docker client could not be created: %s" % e
        return False
    try:
        resolved = resolve_image(client, image, version)
    except Exception as e:
        _UNAVAILABLE_REASONS[image] = "it could not be pulled: %s" % e
        return False
    # An image is only half of it. The other half is whether the daemon that
    # would run it can see the directories PartCAD is going to bind -- see
    # 'mounts_are_shared'. A machine that fails this is one where every part
    # would fail later, in a way that names nothing.
    sources = mount_sources(client, resolved)
    if sources is False:
        _UNAVAILABLE_REASONS[image] = (
            "the Docker daemon cannot see this machine's files, so nothing can be bind-mounted into a "
            "container -- which is what a dev container using the host's Docker socket, or a 'DOCKER_HOST' "
            "on another machine, looks like"
        )
        return False
    # Reaching the files through this container's mounts is only as good as
    # the mounts: a directory the sandbox needs on none of them is a start that
    # fails later (see 'DockerPythonRuntime._mounts'), asked here instead, where
    # "no" still leaves PartCAD another sandbox to choose.
    _SOURCES[image] = sources
    _UNAVAILABLE_REASONS.pop(image, None)
    return not misses(image, [*needed, tempfile.gettempdir(), INSTALL_DIR])


def unbacked(paths, sources) -> list:
    """Which of ``paths`` the daemon cannot bind, given 'mount_sources'; none where it shares this filesystem."""
    if sources is None:
        return []
    return [p for p in paths if p and docker_mount.backed_by(p, sources) is None]


# Whether a directory this process creates is the one the daemon binds, keyed by
# the daemon it was asked of and the image it was asked in. Once per process:
# the answer is a property of how this machine reaches Docker, and that does not
# change while a command runs.
_MOUNTS_SHARED = {}
_MOUNTS_SHARED_GUARD = threading.Lock()

# What the probe writes and looks for. The name is only ever seen in a container
# that is about to be thrown away.
_PROBE_FILE = "partcad-mount-probe"


def mounts_are_shared(client, image: str) -> bool:
    """Whether the sandbox can bind PartCAD's directories into a container at all.

    True where the daemon shares this filesystem, and also where it does not
    but has each directory somewhere it can say -- see :func:`mount_sources`.
    """
    return mount_sources(client, image) is not False


def mount_sources(client, image: str):
    """How the daemon reaches this process's directories: ``None``, a list, or ``False``.

    ``None`` -- it binds *these* directories: an ordinary host, or a daemon in
    this very container.

    A list of (here, daemon-side) pairs -- it does not share this filesystem,
    but this process runs in a container *on that daemon*, and the directories
    PartCAD binds are mounts of that container whose daemon-side locations the
    daemon reported. Binds take their source from there and keep their target,
    so inside the sandbox every path is still the one PartCAD knows (see
    ``docker_mount``). ``PC_DOCKER_MOUNT_SOURCES`` -- ``here=there`` pairs
    separated by ``;`` -- says the same thing by hand, for a setup this cannot
    work out.

    ``False`` -- neither; the sandbox cannot be used here.

    Every part of this sandbox rests on that. PartCAD hands the daemon its own
    paths and expects the container to open its own files there -- the wrappers,
    the package, the environment it just built. A daemon that is not on this
    filesystem resolves those paths against a different one and Docker creates
    whatever is missing, empty and owned by root. Nothing fails at that point:
    the container starts, with directories that are not the ones PartCAD meant,
    and the first thing to go wrong is ``-m venv`` reporting

        Error: [Errno 13] Permission denied: '/home/vscode/.partcad'

    which names neither the daemon nor the mount and sends the reader looking
    for a permissions problem that is not there.

    Two arrangements do this and neither is unusual. A dev container with the
    host's ``/var/run/docker.sock`` bound into it -- "Docker outside of Docker",
    which this repository's own dev container uses -- is the common one, and
    the list above is its answer. ``DOCKER_HOST`` pointing at another machine
    is the other, and has none: this process is not a container over there. So
    each is a probe and not a guess about the environment -- one container that
    looks for a file, asked again with the mapping if it was not found without.
    """
    key = (getattr(getattr(client, "api", None), "base_url", None), image)
    with _MOUNTS_SHARED_GUARD:
        if key in _MOUNTS_SHARED:
            return _MOUNTS_SHARED[key]

    if _probe_mounts(client, image):
        answer = None
    else:
        sources = _declared_sources()
        if sources is None:
            sources = _own_container_sources(client)
        answer = sources if sources and _probe_mounts(client, image, sources) else False
        if answer is False:
            pc_logging.debug(
                "The Docker daemon at %s does not share this filesystem, so the 'docker' sandbox cannot "
                "bind PartCAD's directories into a container." % (key[0],)
            )
        else:
            pc_logging.debug(
                "The Docker daemon at %s does not share this filesystem; binding from where it has "
                "this container's mounts: %s" % (key[0], sources)
            )
    with _MOUNTS_SHARED_GUARD:
        _MOUNTS_SHARED[key] = answer
    return answer


def client_mounts(sources) -> dict:
    """Every directory this process's container has from the daemon, bound where it is here.

    All of them, rather than the ones the context at hand asked for. The
    sandbox container is shared and replaced when the mounts it needs differ,
    and inside one dev container they used to differ for no reason that
    mattered: a test with a temporary '~' needs '/tmp' and the workspace, and
    the daemon with the real one needs '~/.partcad' too. Each removed the
    other's container, and the one whose container went on running commands
    by name in its replacement -- with somebody else's mounts, so that what it
    wrote went where it never looked. One set per dev container, so nothing in
    it ever replaces anything.

    Directories only: a socket or a file bound in (the host's Docker socket,
    the CI runner's command files) is not something a sandbox has any use for,
    and the Docker socket least of all.
    """
    mounts = {}
    for here, there in sorted(sources or ()):
        here = here.rstrip("/") or "/"
        if os.path.isdir(here) and not os.path.islink(here) and here != "/":
            mounts[there.rstrip("/") or "/"] = {"bind": here, "mode": "rw"}
    return mounts


def container_name(image: str, mounts=None) -> str:
    """The sandbox container for ``image`` with ``mounts``: one per image and mount set.

    Named after the image alone, one container served every process on the
    daemon, and any of them needing different mounts replaced it -- a package
    outside the home directory on an ordinary host, another dev container on
    the same machine, a test with a temporary home. Whoever had started it went
    on running commands by name in the replacement, with somebody else's
    mounts: writing where it never looked, reading what was not its own, and
    killed outright if a command was running when it was removed.

    So the mounts are in the name: where each one comes from and where it
    lands. Processes needing the same ones share a container, which is safe
    because they see the same files -- every project under one home directory
    on an ordinary host, everything in one dev container (see 'client_mounts').
    Processes needing different ones each have their own, and never touch each
    other's. Without ``mounts``, the name before '_start' has worked them out.
    """
    name = "pc-sandbox-" + _short(image)
    if not mounts:
        return name
    whose = repr(sorted((source, spec["bind"]) for source, spec in mounts.items()))
    return name + "-" + _short(whose)


def _declared_sources():
    """``PC_DOCKER_MOUNT_SOURCES`` as (here, there) pairs; ``None`` if it is not set."""
    value = os.environ.get("PC_DOCKER_MOUNT_SOURCES", "").strip()
    if not value:
        return None
    pairs = []
    for item in value.split(";"):
        here, sep, there = item.partition("=")
        if sep and here.strip() and there.strip():
            pairs.append((here.strip(), there.strip()))
    return pairs


# What the daemon calls a container's own directory, which is where the files
# it bind-mounts into every container (/etc/hostname, /etc/hosts) come from --
# so a container's mount table names its own id. More reliable than the
# hostname, which a container can be given.
_CONTAINER_ID = re.compile(r"/containers/([0-9a-f]{64})/")


def _own_container_sources(client):
    """This process's container's mounts, as the daemon has them; ``None`` if it is not one of its.

    Binds and volumes alike: a volume's 'Source' is where the daemon keeps it,
    which it can bind from as well as from anywhere else. A tmpfs has no source
    and nothing to bind from.
    """
    candidates = []
    try:
        with open("/proc/self/mountinfo") as f:
            candidates += _CONTAINER_ID.findall(f.read())
    except OSError:
        pass
    candidates.append(socket.gethostname())

    for candidate in dict.fromkeys(candidates):
        try:
            container = client.containers.get(candidate)
        except Exception:
            continue
        sources = [
            (mount["Destination"], mount["Source"])
            for mount in container.attrs.get("Mounts") or []
            if mount.get("Type") in ("bind", "volume") and mount.get("Source") and mount.get("Destination")
        ]
        return sources or None
    return None


def _probe_mounts(client, image: str, sources=None) -> bool:
    """One throwaway container, asked whether it can see a file made here."""
    with tempfile.TemporaryDirectory() as probe:
        marker = os.path.join(probe, _PROBE_FILE)
        with open(marker, "w") as written:
            written.write("partcad")
        # Readable by anyone, because the question is where the daemon looks and
        # not who may read what it finds. A temporary directory is 0700, and on
        # a platform where the container cannot be told to run as this user --
        # Docker Desktop maps ownership itself, so it is not -- that would make
        # a daemon on this very filesystem answer "somewhere else". The real
        # sandbox's mounts keep the permissions they have; only this one file,
        # made to be read once and deleted, is opened up.
        os.chmod(probe, 0o755)
        os.chmod(marker, 0o644)
        try:
            client.containers.run(
                image,
                # 'python3' rather than 'test': the base image contract promises
                # an interpreter under that name and promises nothing about a
                # shell, and a derived image is free to have dropped one.
                command=[
                    CONTAINER_PYTHON,
                    "-c",
                    "import os,sys; sys.exit(0 if os.path.isfile(%r) else 1)" % docker_mount.translate(marker),
                ],
                entrypoint=[],
                volumes=docker_mount.mounts([probe], sources=sources),
                # The same user the sandbox's own container runs as, for the
                # same reason and with the same platform rule -- see
                # '_start_once'. Not decoration: a temporary directory is the
                # host user's and readable by nobody else, so a probe running
                # as the image's user would fail to read its own marker on any
                # machine whose uid is not the image's, report a daemon that is
                # right here as somewhere else, and turn this sandbox off for
                # everybody. Every GitHub runner is such a machine.
                user=("%d:%d" % (os.getuid(), os.getgid())) if platform.system() == "Linux" else None,
                remove=True,
            )
            return True
        except docker.errors.ContainerError:
            # It ran and did not find the file: the directory it was given is
            # not the one made above. This is the answer, not an error.
            return False
        except Exception as e:
            # Anything else -- the image will not run, the daemon refused the
            # mount, a path that cannot be bound at all -- is a sandbox that
            # will not work either, and the caller's fallback is the same.
            pc_logging.debug("The 'docker' sandbox mount probe did not complete: %s" % e)
            return False


@telemetry.instrument()
class DockerPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None, image=None):
        if image is None:
            image = image_for(version or runtime_python.sandbox_versions.DEFAULT_PYTHON_VERSION)
        # The image is part of the sandbox's identity, not just of how it is
        # reached. What pip resolves and what it compiles against depends on the
        # native libraries underneath, and two images do not have the same ones
        # -- so two images at one Python version are two sandboxes, and sharing
        # a directory between them would mean each finding the other's builds.
        super().__init__(ctx, "docker-" + _short(image), version)

        self.image = image
        # Named after the image and, once '_start' knows them, the mounts -- see
        # 'container_name'. It outlives the process that started it, so the
        # next 'pc' command with the same mounts finds it warm.
        self.container_name = container_name(image)
        self._container = None
        # Where the daemon has the directories, when it is not here -- see
        # 'mount_sources'. Set by '_start'.
        self._mount_sources = None

        # The interpreter inside the container, always POSIX. 'exec_name' is
        # 'python.exe' on a Windows host, which is what the base class uses to
        # find an interpreter in an environment -- and the environment here was
        # built by Linux and has 'bin/python' whatever the host is.
        self.exec_name = "python"
        self.exec_path = CONTAINER_PYTHON

    # ----------------------------------------------------------------- paths --

    @property
    def _mounted(self) -> list:
        """The host directories the container needs to see.

        Deliberately few, and on an ordinary machine two. The home directory
        leads because it already contains the state directory holding this
        sandbox and the caches ('~/.partcad'), the package being worked on, and
        usually the installation -- so 'mounts' drops those as nested. The
        temporary directory is the second, and is only nested inside the home
        directory on Windows; on Linux it is '/tmp' and on macOS somewhere
        under '/var/folders', neither of which is. That is the whole set on
        such a machine, and it is the same set for every context -- which is
        what lets one container serve all of them, because a mount set that
        does not vary is a container that never has to be replaced.

        The others are still named because they are not always under it: a
        package on another volume, a system-wide installation, a file an ad-hoc
        command was pointed at somewhere else. Each of those is one more mount
        and one more reason this container is not the last one's.

        All writable, and the home directory is a lot to hand over. That is the
        trade this makes on purpose: the isolation worth having is the
        container, and the mounts are a stopgap for the paths a wrapper is
        handed. See 'docker_mount.mounts'.
        """
        paths = []
        home = os.path.expanduser("~")
        # Not the filesystem root, which is what a broken or absent '~' expands
        # to and is not a thing to bind-mount.
        if home and os.path.isdir(home) and home.rstrip("/\\"):
            paths.append(home)
        # The temporary directory, because a fixed mount is simpler than
        # arranging for nothing to be temporary. Plenty of things land there
        # without asking -- an ad-hoc command's generated package, a factory's
        # intermediate, a caller's own 'mkstemp' -- and each one that a
        # container cannot open is the same bug found again somewhere new. One
        # mount ends the category. It is under the home directory on Windows,
        # where 'mounts' drops it as nested and this costs nothing.
        paths.append(tempfile.gettempdir())
        paths += [self.ctx.user_config.internal_state_dir, INSTALL_DIR]
        root = getattr(self.ctx, "root_path", None)
        if root:
            paths.append(root)
        # What the context asked for on top: a file an ad-hoc command was
        # pointed at, which lives wherever the user keeps it rather than inside
        # the generated package. See 'Context.sandbox_paths'.
        paths += [p for p in getattr(self.ctx, "sandbox_paths", ()) or () if p]
        return paths

    def _mounts(self, sources) -> dict:
        """The binds for '_mounted', from where the daemon has them (see 'mount_sources').

        With ``sources``, a directory the daemon does not have cannot be bound.
        The home directory may go: it is there to cover the others in one mount,
        and each of them is still asked for on its own. Anything else is a path
        a wrapper will be handed and the container will not have, so the
        sandbox is refused here, naming it, rather than failing later on a file
        that is not there.

        And with ``sources`` what is bound is not this context's directories
        but every directory mount of the container this process runs in -- see
        'client_mounts' -- under a name that says whose they are.
        """
        paths = self._mounted
        if sources is not None:
            home = os.path.expanduser("~")
            missing = unbacked([p for p in paths if p != home], sources)
            if missing:
                raise runtime.SandboxUnavailable(
                    "the 'docker' sandbox runs on a Docker daemon that does not share this filesystem, and "
                    "binds from where it keeps this container's mounts -- but %s %s not on any of them. "
                    "Mount %s into this container (a bind or a volume), or name where the daemon has %s "
                    "in PC_DOCKER_MOUNT_SOURCES."
                    % (
                        ", ".join(missing),
                        "is" if len(missing) == 1 else "are",
                        "it" if len(missing) == 1 else "them",
                        "it" if len(missing) == 1 else "them",
                    )
                )
        self._mount_sources = sources
        # Where the daemon is somebody else's, everything this container has
        # from it rather than only what this context asked for -- see
        # 'client_mounts'. Either way the container is named after the result.
        mounts = docker_mount.mounts(paths) if sources is None else client_mounts(sources)
        self.container_name = container_name(self.image, mounts)
        return mounts

    @property
    def _container_home(self) -> str:
        """Where '~' points inside the container. See '_exec'."""
        return os.path.join(self.ctx.user_config.internal_state_dir, "container-home")

    def get_venv_python_path(self, session=None, path=None):
        """Where an environment's interpreter is, as the container sees it.

        The base class asks the *host* whether to look in 'bin' or in 'Scripts'.
        Here the answer is always 'bin': the environment was created by the
        interpreter in a Linux image, and a Windows host reading the same
        directory does not change what is in it.
        """
        if os.name != "nt":
            return super().get_venv_python_path(session=session, path=path)

        if path is None:
            if session is None or not session["dirty"]:
                return self.exec_path
            path = session["path"]
        return "/".join([docker_mount.translate(path), "bin", self.exec_name])

    # ------------------------------------------------------------ container --

    def _resolve_image(self, client) -> str:
        """The image to run, pulled if this machine does not have it yet."""
        return resolve_image(client, self.image, self.version)

    def _start(self):
        """The container for this sandbox, started or reused.

        One per image, shared by every sandbox that named it and reused across
        runs: what a container costs is in the starting, and a command over a
        tree of parts would otherwise pay it per part -- and the next 'pc'
        command finds it still running rather than paying again.

        It is replaced only when what it has mounted is not what this context
        needs, which on an ordinary machine is never: the home directory covers
        everything and the mount set does not vary. A package on another volume
        or an ad-hoc file elsewhere is what makes it vary.

        Under a lock, because the body can remove a container and create
        another with the same name, and two threads doing that at once leave
        one of them holding a container the other has already destroyed.
        """
        if self._container is not None:
            return self._container

        if not runtime.docker_available():
            raise runtime.SandboxUnavailable(
                "the 'docker' sandbox needs a container runtime and there is none here. "
                "Start Docker, or choose another sandbox with 'pythonSandbox'."
            )

        name = self.container_name
        with _start_lock(name):
            # Another thread may have done this while this one waited.
            if self._container is not None:
                return self._container

            client = docker.from_env()
            # Asked before anything is created. A daemon that is not on this
            # filesystem hands the container directories that are not these
            # ones, and every failure after that names something else -- see
            # 'mounts_are_shared'. Only a *declared* 'pythonSandbox: docker'
            # reaches this: where PartCAD chooses, 'image_available' asked the
            # same question first and chose another sandbox.
            sources = mount_sources(client, resolve_image(client, self.image, self.version))
            if sources is False:
                raise runtime.SandboxUnavailable(
                    "the 'docker' sandbox needs a container runtime that can see this machine's files, "
                    "and this one cannot: a directory created here is not the directory it binds. That "
                    "is what a dev container with the host's Docker socket, or a 'DOCKER_HOST' on "
                    "another machine, gives you. Run PartCAD where that daemon is, or choose a sandbox "
                    "that stays here with 'pythonSandbox' -- 'conda' and 'venv' both work."
                )

            mounts = self._mounts(sources)
            for attempt in range(_START_ATTEMPTS):
                container = self._start_once(client, mounts)
                if container is not None:
                    self._container = container
                    return container
                # Lost to another process on this machine. Give its removal or
                # its creation a moment to finish rather than spinning against
                # a name that is briefly neither there nor free.
                time.sleep(_START_RETRY_DELAY * (attempt + 1))

            raise Exception(
                "Could not get the '%s' container for the '%s' sandbox: something else on this "
                "machine kept creating and removing it. Check for another PartCAD run, or for a "
                "container of that name being managed by hand." % (name, self.sandbox)
            )

    def _start_once(self, client, mounts):
        """One attempt at having the container this sandbox wants.

        Returns it, or ``None`` to say the attempt lost a race with another
        process and is worth making again. Only that: anything else Docker
        refuses is raised, because a sandbox that cannot start is a thing to
        report rather than to retry.
        """
        try:
            existing = client.containers.get(self.container_name)
        except docker.errors.NotFound:
            existing = None

        if existing is not None:
            # The name now says which image *and* which mounts, so a container
            # that answers to it should already be the right one. This is the
            # case where it is not: a container left by a PartCAD that derived
            # either of those differently, still on the machine under a name
            # this one also uses.
            #
            # Bind mounts only. An image may declare a VOLUME of its own, which
            # Docker adds as a mount PartCAD never asked for and cannot match --
            # comparing those in would replace such an image's container before
            # every single command.
            #
            # Where each one lands is compared as well as whether it may be
            # written, since a destination is derived from its source and the
            # run where they disagree is exactly the stale container above.
            existing_binds = {
                mount.get("Source"): (mount.get("Destination"), bool(mount.get("RW", True)))
                for mount in (existing.attrs.get("Mounts") or [])
                if mount.get("Type") == "bind"
            }
            wanted_binds = {host: (spec["bind"], spec["mode"] != "ro") for host, spec in mounts.items()}
            if existing_binds == wanted_binds:
                if existing.status != "running":
                    try:
                        existing.start()
                    except docker.errors.NotFound:
                        return None  # removed between the look-up and the start
                return existing

            pc_logging.debug(
                "Replacing %s: it is mounted %s rather than %s"
                % (self.container_name, sorted(existing_binds.items()), sorted(wanted_binds.items()))
            )
            try:
                existing.remove(force=True)
            except docker.errors.NotFound:
                pass  # somebody else removed it, which is the outcome asked for
            except docker.errors.APIError as e:
                if e.status_code != 409:
                    raise
                # "removal of container ... is already in progress": another
                # process wants it gone too. Let it finish rather than trying to
                # create the replacement while the name is still taken.
                return None

        image = self._resolve_image(client)
        os.makedirs(self._container_home, exist_ok=True)
        for host, spec in mounts.items():
            # Made here, where this process sees it: with mount sources the key
            # is the daemon's name for the directory, which is nothing here.
            os.makedirs(spec["bind"] if self._mount_sources is not None else host, exist_ok=True)
            pc_logging.debug("Sandbox mount: %s -> %s" % (host, spec["bind"]))

        with pc_logging.Action("Container", self.version, self.container_name):
            try:
                return client.containers.run(
                    image,
                    command=KEEPALIVE,
                    entrypoint=[],
                    name=self.container_name,
                    detach=True,
                    volumes=mounts,
                    # So that what the sandbox writes is owned by whoever is running
                    # PartCAD. Linux only: there a bind mount passes uids straight
                    # through and files would otherwise come back owned by the
                    # image's user, while Docker Desktop maps ownership itself and
                    # naming a uid that does not exist in the image breaks it.
                    user=("%d:%d" % (os.getuid(), os.getgid())) if platform.system() == "Linux" else None,
                    labels={"partcad.container": "1", "partcad.image": "1"},
                    auto_remove=False,
                )
            except docker.errors.APIError as e:
                if e.status_code != 409:
                    raise
                # The name is taken: another process created it between the
                # look-up above and here. Go round and inspect *that* container
                # -- it is named after these mounts, so it is very likely the
                # one this sandbox was about to make.
                return None

    # ----------------------------------------------------------- execution --

    def _exec(self, cmd, cwd=None) -> list:
        """``cmd`` as a command line that runs it inside this sandbox's container.

        Through the 'docker' command rather than the SDK's 'exec_run', so that
        everything the base runtime does around a subprocess -- the process
        slots, the timeout, killing a child whose await was cancelled -- goes on
        applying unchanged to what is now a container.
        """
        self._start()
        argv = ["docker", "exec", "-i"]
        # A home directory the process can write to. PartCAD runs the container
        # as the *host's* uid on Linux, and that uid has no entry in the image's
        # '/etc/passwd' -- so Docker sets 'HOME=/', which is root-owned, and
        # every library that keeps a cache under '~/.cache' fails to make one.
        # 'ezdxf' says so on stderr, and a wrapper that writes to stderr is a
        # wrapper PartCAD reports as having failed: every SVG and PNG render in
        # a container came back as an error over a cache nobody needed.
        #
        # Under the internal state directory because that is mounted, writable,
        # and outlives the container -- so a cache written there is a cache the
        # next run still has, which is what a cache is for.
        argv += ["-e", "HOME=" + docker_mount.rewrite(self._container_home, self._mounted)]
        if cwd:
            argv += ["-w", docker_mount.rewrite(cwd, self._mounted)]
        argv.append(self.container_name)
        argv += [docker_mount.rewrite(str(a), self._mounted) for a in cmd]
        return argv

    def _spawn(self, cmd, cwd=None, env=None):
        """The same command, run in this sandbox's container.

        Overriding the launch rather than a 'run' method is what makes the rest
        of 'PythonRuntime' apply unchanged: the session v-envs, the dependency
        installs and their guards, the environment lock, the flags, and the
        diagnostics for an interpreter that died without saying anything all go
        on working, and every one of them now happens over there.

        'cwd' becomes '-w' inside the container and must not also be applied to
        the 'docker' process itself, which runs wherever PartCAD does. 'env' is
        dropped for the same reason: it would put variables on the client rather
        than on the interpreter, which is the opposite of the intent.
        """
        return self._exec(cmd, cwd), None, None

    # -------------------------------------------------------- provisioning --

    def _create_locked(self) -> list:
        """The command that builds the environment, or an empty list.

        The same shape as the 'venv' sandbox's, and for the same reason: an
        environment is built once and used by every command afterwards. What
        differs is only where it is built.
        """
        if self._environment_built:
            return []
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        return ["-m", "venv", "--upgrade-deps", docker_mount.rewrite(self.path, self._mounted)]

    @property
    def _host_venv_python(self) -> str:
        """The environment's interpreter as a path on *this* machine.

        Which is where it has to be checked for: the container is not consulted
        about whether it needs to build one, and the whole point of mounting at
        identical paths is that the host can answer.
        """
        return os.path.join(self.path, "bin", "python")

    @property
    def _environment_built(self) -> bool:
        """Whether the environment is there, asked in a way the host can answer.

        'lexists', not 'exists'. A virtual environment's 'bin/python' is a
        symlink to the interpreter that built it, and that interpreter is the
        *image's* -- '/usr/local/bin/python3' in a `python:*-slim`. The host is
        under no obligation to have a file at that path, so the symlink dangles
        here and 'os.path.exists' follows it and says no.

        Which is the whole trick this sandbox turns: the environment is one the
        host can see and pip can install into, and its interpreter is one only
        the container can run. Asking whether the host can run it was asking the
        wrong question, and the answer was to build the environment again, every
        time, and then call a successful build a failure.
        """
        return os.path.lexists(self._host_venv_python)

    def _created(self, exitcode, stderr) -> None:
        """Accept the environment, or fail with what actually went wrong.

        'run_*_locked' reports an exit code rather than raising, so a '-m venv'
        that failed would otherwise be stepped straight past and the first thing
        anybody saw would be pip failing on a missing file.
        """
        if exitcode != 0 or not self._environment_built:
            raise Exception(
                "Failed to create the '%s' sandbox at %s in %s: %s"
                % (
                    self.sandbox,
                    self.path,
                    self.image,
                    (stderr or "").strip() or "'-m venv' exited with %s" % exitcode,
                )
            )
        self.exec_path = docker_mount.rewrite(self._host_venv_python, self._mounted)

    def once(self):
        if self.provisioned:
            return
        with self.sync_lock(write=True):
            command = self._create_locked()
            if command:
                with pc_logging.Action("Docker", self.version, self.path):
                    exitcode, _, stderr = self.run_onced_locked(command)
                self._created(exitcode, stderr)
            elif self._environment_built:
                self.exec_path = docker_mount.rewrite(self._host_venv_python, self._mounted)
        super().once()

    async def once_async(self):
        if self.provisioned:
            return
        async with self.async_lock(write=True):
            command = self._create_locked()
            if command:
                with pc_logging.Action("Docker", self.version, self.path):
                    exitcode, _, stderr = await self.run_async_onced_locked(command)
                self._created(exitcode, stderr)
            elif self._environment_built:
                self.exec_path = docker_mount.rewrite(self._host_venv_python, self._mounted)
        await super().once_async()
