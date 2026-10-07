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

The container itself is started the way every container PartCAD starts is --
`partcad_utils.containers` names it after the image and the mounts, labels it,
puts the service in it and replaces a stale one -- so what is particular to this
module is only how commands reach it, and that depends on the transfer mode:

* ``mount`` -- this class. The environment is on a mounted directory and every
  command runs through ``docker exec``, so that everything ``PythonRuntime``
  does around a subprocess -- the process slots, the timeout, killing a child
  whose await was cancelled -- goes on applying unchanged.
* ``upload`` -- `DockerUploadPythonRuntime`. Nothing here is visible over there,
  so the environment lives in a volume on the daemon's side and every command
  goes through the container's service with its files, exactly as the
  ``remote`` sandbox's commands do through `partcad-service-remote-docker` --
  by the same code, without the hop.
"""

import hashlib
import os
import socket  # noqa: F401 - the tests patch its 'gethostname' through this module
import tempfile
import threading
from typing import Optional

import docker

from partcad_utils import container_image, containers

from . import container_mounts, docker_image, docker_mount
from . import logging as pc_logging
from . import runtime, runtime_python, runtime_python_remote, telemetry

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


def misses(image: str, needed, mode: str = containers.MOUNT) -> bool:
    """Whether the daemon cannot bind one of ``needed`` for ``image``; records why, as 'image_available' does.

    Separate from 'image_available' because the directories are a context's
    and the answer to that question is not: asked after it said yes. Never in
    ``upload`` mode, which binds nothing from here.
    """
    if mode == containers.UPLOAD:
        return False
    missing = unbacked(needed, _SOURCES.get(image))
    if missing:
        _UNAVAILABLE_REASONS[image] = (
            "the Docker daemon does not share this filesystem, and %s %s not on any of the mounts it could "
            "bind from instead" % (", ".join(missing), "is" if len(missing) == 1 else "are")
        )
    return bool(missing)


def image_available(image: str, version: str = "", needed=(), mode: str = containers.MOUNT) -> bool:
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
    # In 'upload' mode that is all of it: nothing from here is bound, so what
    # the daemon can see of this machine does not matter.
    if mode == containers.UPLOAD:
        _UNAVAILABLE_REASONS.pop(image, None)
        return True
    # An image is only half of it. The other half is whether the daemon that
    # would run it can see the directories PartCAD is going to bind -- see
    # 'mounts_are_shared'. A machine that fails this is one where every part
    # would fail later, in a way that names nothing.
    sources = mount_sources(client, resolved)
    if sources is False:
        _UNAVAILABLE_REASONS[image] = (
            "the Docker daemon cannot see this machine's files, so nothing can be bind-mounted into a "
            "container -- which is what a 'DOCKER_HOST' on another machine looks like. Set "
            "'useDockerRemote: true' to send the files instead"
        )
        return False
    # Reaching the files through this container's mounts is only as good as
    # the mounts: a directory the sandbox needs on none of them is a start that
    # fails later (see 'DockerPythonRuntime._mounts'), asked here instead, where
    # "no" still leaves PartCAD another sandbox to choose.
    _SOURCES[image] = sources
    _UNAVAILABLE_REASONS.pop(image, None)
    return not misses(image, [*needed, tempfile.gettempdir(), INSTALL_DIR])


# How the daemon reaches this process's directories lives in partcad_utils now,
# where a client can ask it too; these are the names everything here (and the
# tests) reach it by. One module, so one cache: '_MOUNTS_SHARED' is the dict.
from partcad_utils.daemon_mounts import (  # noqa: E402,F401 - re-exported
    _CONTAINER_ID,
    _MOUNTS_SHARED,
    _MOUNTS_SHARED_GUARD,
    _PROBE_FILE,
    _declared_sources,
    _own_container_sources,
    _probe_mounts,
    client_mounts,
)
from partcad_utils.daemon_mounts import mount_sources as _mount_sources  # noqa: E402
from partcad_utils.daemon_mounts import (  # noqa: E402,F401 - re-exported
    mounts_are_shared,
    unbacked,
)


def mount_sources(client, image: str):
    """See `partcad_utils.daemon_mounts.mount_sources`; asked with the sandbox image's interpreter."""
    return _mount_sources(client, image, CONTAINER_PYTHON)


def sandbox_spec(image: str, mounts) -> containers.ContainerSpec:
    """The container a ``mount``-mode sandbox for ``image`` with ``mounts`` runs in.

    One per image and mount set, as ever: processes needing the same mounts see
    the same files and may share a container, and processes needing different
    ones each get their own (see 'client_mounts' for why a dev container asks
    for one set). The name is derived from this by 'containers.container_name'.
    """
    return containers.ContainerSpec(
        role="sandbox",
        image=image,
        mode=containers.MOUNT,
        mounts=dict(mounts),
        user=container_mounts.host_user(),
        allowed_commands={CONTAINER_PYTHON: None},
    )


@telemetry.instrument()
class DockerPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None, image=None):
        own_image = image is None
        if own_image:
            image = image_for(version or runtime_python.sandbox_versions.DEFAULT_PYTHON_VERSION)
        # The image is part of the sandbox's identity, not just of how it is
        # reached. What pip resolves and what it compiles against depends on the
        # native libraries underneath, and two images do not have the same ones
        # -- so two images at one Python version are two sandboxes, and sharing
        # a directory between them would mean each finding the other's builds.
        super().__init__(ctx, "docker-" + _short(image), version)

        self.image = image
        # Named after the image and the mounts -- see 'sandbox_spec'. Worked
        # out here for an ordinary host, where it is final; '_start' works it
        # out again from what the daemon really sees, which differs only in a
        # dev container. It outlives the process that started it, so the next
        # 'pc' command with the same mounts finds it warm.
        self.container_name = containers.container_name(sandbox_spec(image, docker_mount.mounts(self._mounted)))
        self._container = None
        # One start at a time per sandbox. Across sandboxes and processes the
        # name is the lock; see 'containers.acquire'.
        self._start_guard = threading.Lock()
        # Where the daemon has the directories, when it is not here -- see
        # 'mount_sources'. Set by '_start'.
        self._mount_sources = None

        # The interpreter inside the container, always POSIX. 'exec_name' is
        # 'python.exe' on a Windows host, which is what the base class uses to
        # find an interpreter in an environment -- and the environment here was
        # built by Linux and has 'bin/python' whatever the host is.
        self.exec_name = "python"
        self.exec_path = CONTAINER_PYTHON

        # PartCAD's own images carry a 'pycairo' wheel (PIP_FIND_LINKS, see
        # 'tools/containers/python/Dockerfile') and no compiler. pip ranks a
        # newer sdist on PyPI above that wheel, so the day pycairo releases,
        # every PNG render in a published image tries to compile it and fails.
        # Only for our images: one a package names may have a compiler and no
        # wheel, and building from source is then what works there.
        if own_image:
            self.pip_install_flags += ["--only-binary", "pycairo"]

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
        self.container_name = containers.container_name(sandbox_spec(self.image, mounts))
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

        Named after the image and the mounts, so a context needing other mounts
        gets a container of its own rather than replacing one somebody else is
        running commands in; on an ordinary machine the mount set does not vary
        and there is one. Finding it, checking it is really the container that
        name stands for, starting it and racing other processes for it are all
        'containers.acquire'.
        """
        if self._container is not None:
            return self._container

        if not runtime.docker_available():
            raise runtime.SandboxUnavailable(
                "the 'docker' sandbox needs a container runtime and there is none here. "
                "Start Docker, or choose another sandbox with 'pythonSandbox'."
            )

        client = docker.from_env()
        # Asked before anything is created. A daemon that is not on this
        # filesystem hands the container directories that are not these ones,
        # and every failure after that names something else -- see
        # 'mounts_are_shared'. Only a *declared* 'pythonSandbox: docker' reaches
        # this: where PartCAD chooses, 'image_available' asked the same question
        # first and chose another sandbox.
        try:
            resolved = resolve_image(client, self.image, self.version)
        except Exception as e:
            raise runtime.SandboxUnavailable("the 'docker' sandbox cannot get %s: %s" % (self.image, e))
        sources = mount_sources(client, resolved)
        if sources is False:
            raise runtime.SandboxUnavailable(
                "the 'docker' sandbox needs a container runtime that can see this machine's files, "
                "and this one cannot: a directory created here is not the directory it binds. That is "
                "what a 'DOCKER_HOST' on another machine gives you. Set 'useDockerRemote: true' "
                "(PC_USE_DOCKER_REMOTE=true) to send the files with each command instead, or choose a "
                "sandbox that stays here with 'pythonSandbox' -- 'conda' and 'venv' both work."
            )

        mounts = self._mounts(sources)
        # Made here, before the container binds them: a directory the daemon
        # creates for a bind is root's, and nothing written later can fix that.
        os.makedirs(self._container_home, exist_ok=True)
        for host, spec in mounts.items():
            # With mount sources the key is the daemon's name for the
            # directory, which is nothing here; the bind is where it is here.
            os.makedirs(spec["bind"] if self._mount_sources is not None else host, exist_ok=True)
            pc_logging.debug("Sandbox mount: %s -> %s" % (host, spec["bind"]))

        with self._start_guard:
            if self._container is None:
                endpoint = container_mounts.acquire(sandbox_spec(self.image, mounts), client=client)
                self.container_name = endpoint.name
                self._container = endpoint.container
        return self._container

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


# --------------------------------------------------------------------------- #
# 'upload' mode                                                                #
# --------------------------------------------------------------------------- #

# The containers and the environments in them that this process holds in
# 'upload' mode: the same pool and the same provisioning
# 'partcad-service-remote-docker' holds, kept here instead of over there.
_LOCAL = None
_LOCAL_GUARD = threading.Lock()


def _local_service():
    """This process's pool and environments, made on first use."""
    global _LOCAL
    from . import remote_docker, remote_sandbox

    with _LOCAL_GUARD:
        if _LOCAL is None:
            pool = remote_docker.ContainerPool(lambda image: remote_docker.start(image, role="sandbox"))
            environments = remote_sandbox.Environments(
                lambda image, command, lock: remote_sandbox.forward(pool, image, command, {"lock": lock})
            )
            _LOCAL = (pool, environments)
        return _LOCAL


class _InProcessService:
    """`partcad-service-remote-docker`'s ``execute``, called here rather than over HTTP.

    The same function, so a sandbox in ``upload`` mode provisions its
    environment, prepends its interpreter and moves its files exactly as a
    ``remote`` one does -- one implementation of all of that, not two.
    """

    def execute(self, command, params, timeout=None):
        from . import remote_sandbox

        pool, environments = _local_service()
        try:
            result = remote_sandbox.execute(pool, environments, {"command": list(command), **params}, timeout=timeout)
        except Exception as e:
            return {"error": {"message": str(e)}}
        return {"result": result}

    async def execute_async(self, command, params, timeout=None):
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.execute(command, params, timeout))


class DockerUploadPythonRuntime(runtime_python_remote.RemotePythonRuntime):
    """The ``docker`` sandbox when the daemon cannot see this machine's files.

    Which is what ``useDockerRemote`` says. Nothing is mounted: the environment
    lives in a volume on the daemon's side, every command goes through the
    container's service carrying the directories it reads, and what it writes
    comes back with the answer. That is the ``remote`` sandbox exactly, minus
    the service in the middle -- so it *is* that sandbox, talking to its
    containers itself.
    """

    SANDBOX_PREFIX = "docker-upload-"

    def __init__(self, ctx, version=None, image=None):
        super().__init__(ctx, version, image=image, endpoint="in-process")

    def _client(self):
        if not runtime.docker_available():
            raise runtime.SandboxUnavailable(
                "the 'docker' sandbox needs a container runtime and there is none here. "
                "Start Docker, or choose another sandbox with 'pythonSandbox'."
            )
        return _InProcessService()
