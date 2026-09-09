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
from typing import Optional

import docker

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


def image_for(version: str, release: Optional[str] = None) -> str:
    """PartCAD's own base image for this Python version."""
    if release is None:
        from . import __version__

        release = __version__
    return "%s:%s-py%s" % (BASE_IMAGE, release, version)


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


def image_available(image: str, version: str = "") -> bool:
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
        return False
    try:
        client = docker.from_env()
    except Exception:
        return False
    try:
        resolve_image(client, image, version)
        return True
    except Exception:
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
        self.container_name = "pc-sandbox-" + _short(image)
        self._container = None

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

        The internal state directory, which holds this sandbox and the caches,
        and the context root, which holds the package being worked on. Nothing
        else: a sandbox that mounted the whole filesystem would be a sandbox in
        name only.
        """
        paths = [self.ctx.user_config.internal_state_dir]
        root = getattr(self.ctx, "root_path", None)
        if root:
            paths.append(root)
        return paths

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
        tree of parts would otherwise pay it per part.
        """
        if self._container is not None:
            return self._container

        if not runtime.docker_available():
            raise runtime.SandboxUnavailable(
                "the 'docker' sandbox needs a container runtime and there is none here. "
                "Start Docker, or choose another sandbox with 'pythonSandbox'."
            )

        client = docker.from_env()
        mounts = docker_mount.mounts(self._mounted)
        try:
            existing = client.containers.get(self.container_name)
            # The name says which image, and nothing about what is mounted --
            # but the context root is mounted too, and that is per package. A
            # container started while working on one package cannot see another,
            # so reusing it by name alone made every command that named a file
            # under the second package's root fail on a path that is not there.
            visible = {mount.get("Source") for mount in (existing.attrs.get("Mounts") or [])}
            if set(mounts).issubset(visible):
                if existing.status != "running":
                    existing.start()
                self._container = existing
                return existing
            pc_logging.debug("Replacing %s: it cannot see %s" % (self.container_name, sorted(set(mounts) - visible)))
            existing.remove(force=True)
        except docker.errors.NotFound:
            pass

        image = self._resolve_image(client)
        for host, spec in mounts.items():
            os.makedirs(host, exist_ok=True)
            pc_logging.debug("Sandbox mount: %s -> %s" % (host, spec["bind"]))

        with pc_logging.Action("Container", self.version, self.container_name):
            self._container = client.containers.run(
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
        if os.path.exists(self._host_venv_python):
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

    def _created(self, exitcode, stderr) -> None:
        """Accept the environment, or fail with what actually went wrong.

        'run_*_locked' reports an exit code rather than raising, so a '-m venv'
        that failed would otherwise be stepped straight past and the first thing
        anybody saw would be pip failing on a missing file.
        """
        if exitcode != 0 or not os.path.exists(self._host_venv_python):
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
            elif os.path.exists(self._host_venv_python):
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
            elif os.path.exists(self._host_venv_python):
                self.exec_path = docker_mount.rewrite(self._host_venv_python, self._mounted)
        await super().once_async()
