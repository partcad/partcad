#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The environment a ``remote`` sandbox runs in, kept on the container's side.

A sandbox is a virtual environment on a disk, and for ``remote`` that disk
cannot be the caller's -- the caller may not even be the same machine. So the
service owns it: it creates the environment inside the container, installs into
it, and prepends its interpreter to whatever the caller asked to run. The client
sends what it wants done and never learns where the environment is.

Which is the whole reason to put it here rather than mirror it on the client.
Guards that say "numpy is installed" belong on the same disk as the ``numpy``
they describe; a client holding them would be a client guessing about a machine
it cannot see, and would guess wrong the first time a volume was removed.

The environment lives in a Docker **volume** mounted into the container, not in
the container's own filesystem. A container is cattle -- retired when idle,
removed by ``pc system prune``, lost on a restart -- and an environment that went
with it would be rebuilt, and re-downloaded, several times a day.

Nothing here talks to Docker or to a container. It is handed a way to run a
command over there, which is what makes the sequence testable: what is worth
pinning is *which* commands are run, in what order, and how often.
"""

import base64
import json
import threading
from typing import Callable, Optional

from partcad_utils import containers
from partcad_utils.json_rpc_client import RuntimeJsonRpcClient

from . import sandbox_versions
from .process_crash import failure_detail

# Where the volume is mounted inside every container this service starts. Fixed
# rather than configurable: the client never sees it, and a path the caller
# could choose would be a caller choosing where to write inside somebody else's
# container.
SANDBOX_ROOT = "/pc-sandbox"

# What the image's own interpreter may be called *to the service inside it*, in
# the order they are tried. That service takes a command by the name its
# allowlist gives it. PartCAD's base image pins "python" to its interpreter
# (see `tools/containers/README.md`), and that name comes first so that an
# image saying which interpreter is its own is taken at its word. "python3" is
# second, for an image that was not built on that base and has only the name
# Debian and Ubuntu install, with no "python" at all: Gazebo's, ROS's, anything
# on a stock distribution. Which of the two an image has is asked of it (see
# `Environments`) rather than found out from a refusal. The environment's own
# interpreter is a path rather than a name -- it did not exist when the image
# was built -- and the service recognises it by where it is.
IMAGE_PYTHONS = ("python", "python3")


def volume_name(image: str) -> str:
    """The volume holding the environments for one image.

    Per image, for the same reason a sandbox directory is: what pip resolves and
    what it compiles against depend on the native libraries underneath, and two
    images do not have the same ones.
    """
    import hashlib

    return "pc-sandbox-" + hashlib.sha256(image.encode()).hexdigest()[:12]


# Raised when the environments an earlier release built can be wrong in a way
# this one cannot see from outside them, so that they are built again beside the
# old ones rather than trusted. A volume outlives every release that writes to
# it, and pip, asked about a damaged environment, says everything is installed.
#
# 2: until 'Environments._install' forced CadQuery's OCP back over the novtk
# build build123d brings, every environment built here that held both had the
# novtk one, and every CadQuery part in it failed to import. The old directory
# stays in the volume until the volume is removed.
GENERATION = 2


def environment_path(version: str) -> str:
    """Where the environment for one Python version lives inside the volume."""
    return "%s/v%d-env-%s" % (SANDBOX_ROOT, GENERATION, version)


def interpreter_path(version: str) -> str:
    """The interpreter to prepend to whatever the caller asked to run."""
    return "%s/bin/python" % environment_path(version)


def lock_for(version: str, exclusive: bool) -> dict:
    """The lock guarding one environment, as the container service takes it.

    Held exclusively by every command that builds or installs into the
    environment, and shared by every command that runs out of it. Not this
    service's own gate, which guards only the processes that share *it*: in
    'upload' mode every PartCAD process keeps an `Environments` of its own over
    one volume, and the service pool may run several containers on it, so the
    only thing all of them share is the volume -- and that is where the lock is.
    """
    return {"path": environment_path(version) + ".lock", "exclusive": exclusive}


def pip_installed(stdout: Optional[str]) -> bool:
    """Whether 'pip install --quiet --report -' installed anything, from what it printed.

    The report and not pip's log, because the log is the image's to configure:
    one setting 'PIP_QUIET' or 'quiet' in its pip.conf hides "Successfully
    installed", and with it the repair '_install' exists to trigger. A configured
    verbosity can outweigh '--quiet' as well and put the log in front of the
    report; that log says "Successfully installed" when anything was, so that is
    what is read then.
    """
    try:
        report = json.loads(stdout or "")
    except ValueError:
        return "Successfully installed" in (stdout or "")
    return isinstance(report, dict) and bool(report.get("install"))


class Environments:
    """The environments this service has built, and what is installed in them.

    ``run`` is how a command reaches the container -- the service passes
    something that forwards over JSON-RPC, and a test passes something that
    records. It is called as ``run(image, command, lock)``, ``lock`` being
    `lock_for` the environment, and must return ``(exit_code, stdout, stderr)``.

    ``which`` is how the container is asked which of `IMAGE_PYTHONS` it has,
    called as ``which(image, names)`` and answering what the service's ``which``
    does (see `which` below): a path for each name it has, None for each it
    does not, or None for no answer at all. Without it the first name is used
    unasked, which is right only for an image known to have it.
    """

    def __init__(
        self,
        run: Callable[[str, list], tuple],
        which: Optional[Callable[[str, list], Optional[dict]]] = None,
    ):
        self._run = run
        self._which = which
        self._lock = threading.Lock()
        # (image, version) -> set of requirements already installed there.
        self._installed = {}
        self._built = set()
        # image -> the name its interpreter answers to; see '_image_python'.
        self._pythons = {}
        # (image, version) -> requirements whose files an install since has
        # overwritten, so that their next install is forced; see '_install'.
        self._clobbered = {}
        # One lock per environment, so that two callers wanting two different
        # images do not queue behind each other's pip.
        self._gates = {}

    def _gate(self, key) -> threading.Lock:
        with self._lock:
            return self._gates.setdefault(key, threading.Lock())

    def ensure(self, image: str, version: str, requirements: Optional[list] = None) -> str:
        """Make sure the environment exists and holds ``requirements``.

        Returns the interpreter to run things with. Idempotent, and cheap after
        the first call for a given environment: what it costs then is a
        dictionary lookup, not a round trip to the container.
        """
        key = (image, version)
        requirements = list(requirements or [])

        with self._gate(key):
            if key not in self._built:
                self._create(image, version)
                with self._lock:
                    self._built.add(key)
                    self._installed.setdefault(key, set())

            # In order, and decided one at a time rather than up front: an
            # install can overwrite what an earlier one put there, and the list
            # is ordered so that the repair comes after it (see '_install').
            for requirement in requirements:
                with self._lock:
                    clobbered = self._clobbered.setdefault(key, set())
                    force = requirement in clobbered
                    if requirement in self._installed.setdefault(key, set()) and not force:
                        continue
                replaced = self._install(image, version, requirement, force=force)
                with self._lock:
                    self._installed[key].add(requirement)
                    clobbered.discard(requirement)
                    if replaced:
                        for other in sandbox_versions.GUARD_INVALIDATED_BY.get(requirement, ()):
                            self._installed[key].discard(other)
                            clobbered.add(other)

        return interpreter_path(version)

    def _create(self, image: str, version: str) -> None:
        """Build the environment, if the volume does not already hold one.

        '--upgrade-deps' rather than a bare '-m venv': a fresh environment's
        bundled pip is as old as the image, and the first thing anybody does
        with this is install something.
        """
        exitcode, _, stderr = self._run(
            image,
            [self._image_python(image), "-m", "venv", "--upgrade-deps", environment_path(version)],
            lock_for(version, exclusive=True),
        )
        if exitcode != 0:
            raise RuntimeError(
                "Could not create the remote environment for Python %s in %s: %s"
                % (version, image, failure_detail(stderr, exitcode))
            )

        # What was built, not what was asked for. The version picks the
        # directory; the interpreter comes from the image, and an image a
        # package named is under no obligation to carry the version the package
        # also asked for. Without this the mismatch is silent until something
        # imports a wheel built for the other one.
        exitcode, stdout, stderr = self._run(
            image,
            [interpreter_path(version), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            lock_for(version, exclusive=False),
        )
        built = (stdout or "").strip()
        if exitcode != 0 or built != version:
            # Said with the way out, because the version asked for is rarely
            # one anybody chose: an implementation that states none is given
            # PartCAD's default, and the one place that knows what its image
            # carries is the implementation naming that image.
            raise RuntimeError(
                "The remote environment for Python %s in %s is Python %s: that image carries a different "
                "interpreter than the version asked for. Declare the version the image carries "
                "('pythonVersion') beside the 'dockerImage' that names it." % (version, image, built or "unknown")
            )

    def _image_python(self, image: str) -> str:
        """The first of `IMAGE_PYTHONS` the image has, asked once per image.

        An answer naming neither is a refusal here, with both names in it:
        anything else ends in the service turning down the first name, and
        nothing in that says the second was looked for too. No answer at all
        leaves the first name to be tried, so that a service that could not be
        asked fails the way it did before it could be -- and is not remembered:
        no answer is what a timeout gives too, and a guess kept for an image
        with only 'python3' would fail every build in it until the container
        went.
        """
        with self._lock:
            if image in self._pythons:
                return self._pythons[image]
        if self._which is None:
            return IMAGE_PYTHONS[0]
        found = self._which(image, list(IMAGE_PYTHONS))
        if found is None:
            return IMAGE_PYTHONS[0]
        name = next((n for n in IMAGE_PYTHONS if found.get(n)), None)
        if name is None:
            raise RuntimeError(
                "%s has no Python interpreter on its PATH (looked for %s), so no environment can be "
                "built in it. Name an image that has one." % (image, " and ".join(IMAGE_PYTHONS))
            )
        with self._lock:
            self._pythons[image] = name
        return name

    def _install(self, image: str, version: str, requirement: str, force: bool = False) -> bool:
        """Install one requirement; whether pip really installed anything.

        That answer is what the overwritten files are tracked by. build123d
        depends on 'cadquery-ocp-novtk', which writes the same OCP module as
        CadQuery's 'cadquery-ocp' without the VTK half "import cadquery" needs
        (see 'sandbox_versions.GUARD_INVALIDATED_BY'). The base requirements end
        with 'cadquery-ocp' to put it back, and pip, seeing it installed, did
        nothing -- so every CadQuery part in an environment built here failed
        on "cannot import name 'IVtkOCC_Shape'". After an install that replaced
        files, the next install of what it overwrote is forced, as the local
        sandboxes force theirs; one that found everything in place replaced
        nothing, so a process finding the environment already built forces no
        reinstall of the CAD stack.
        """
        # '--prefer-binary' for the reason every other sandbox installs with it
        # (see 'pip_install_flags' in 'runtime_python'): a newer release with no
        # wheel for the image is a compile that fails, an older one with a wheel
        # is an install that works.
        #
        # '--report -' is what says what was installed, and '--quiet' keeps
        # pip's log out of the stream it is written to (see 'pip_installed').
        command = [interpreter_path(version), "-m", "pip", "install", "--no-input", "--prefer-binary"]
        command += ["--quiet", "--report", "-"]
        if force:
            # With its dependencies, for the reason 'FORCE_REINSTALL_FLAGS' in
            # 'runtime_python' gives: the VTK build fails to load without VTK.
            command.append("--force-reinstall")
        exitcode, stdout, stderr = self._run(image, command + [requirement], lock_for(version, exclusive=True))
        if exitcode != 0:
            raise RuntimeError(
                "Could not install '%s' into the remote environment for Python %s in %s: %s"
                % (requirement, version, image, failure_detail(stderr, exitcode))
            )
        return pip_installed(stdout)

    def forget(self, image: str) -> None:
        """Say the containers for this image are gone, so its environments are unknown.

        Not that they are *deleted* -- the volume outlives the container, which
        is the point of it. What is forgotten is only this service's belief
        about what is in there, so the next request re-checks rather than
        assuming a package is installed because a previous process installed it.

        What an install has overwritten is kept: that is a fact about the
        volume, which is still there, and a repair that had not run yet when
        the container went is still owed.
        """
        with self._lock:
            for key in [k for k in self._built if k[0] == image]:
                self._built.discard(key)
                self._installed.pop(key, None)
            self._pythons.pop(image, None)


def _decoded(value) -> str:
    """What a command wrote, which the container sends base64-encoded."""
    return base64.b64decode(value).decode("utf-8", errors="replace") if value else ""


def _message(error) -> str:
    """The sentence out of a JSON-RPC error object, wherever it was nested.

    flask_jsonrpc wraps an exception the view raised: the useful sentence is
    under 'data', and 'message' at the top is "Server error".
    """
    if isinstance(error, dict):
        data = error.get("data")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        if error.get("message"):
            return str(error["message"])
    return str(error)


def _lost(pool, lease, environments=None):
    """How the container behind ``lease`` stopped, having let go of it; None while it runs.

    Asked when a container gave no answer at all, which is what a container
    whose service was killed -- by the out-of-memory killer, most likely, the
    service being a process in the container like any other -- looks like from
    here. Without it the pool went on handing that container out, and every
    command after the one that died failed the same way until the pool retired
    it as idle. The next request for the image starts it again (see
    `ContainerPool.discard`).

    The one place here that asks Docker anything, and only of the container
    object the pool was handed with the lease.
    """
    why = containers.stopped(lease.container)
    if why is None:
        return None
    pool.discard(lease)
    if environments is not None:
        environments.forget(lease.image)
    return "The container serving '%s' %s; it is started again for the next command." % (lease.image, why)


def forward(pool, image: str, command: list, params: dict = None) -> tuple:
    """Run one command in the container for ``image``, as (exit code, out, err).

    What ``Environments`` is given to provision with, and what a forwarded
    request goes through, so both reach a container the same way.
    """
    lease = pool.acquire(image)
    try:
        host, port = lease.endpoint.rsplit(":", 1)
        answer = RuntimeJsonRpcClient(host, int(port), token=lease.token).execute(command, params or {})
        if not answer:
            return 1, "", _lost(pool, lease) or "The container serving '%s' returned no response" % image
        # The envelope, not the payload: the client returns what the container
        # replied with, and what is in it is base64. Reading 'exit_code' off the
        # envelope found nothing, so every command -- a provisioning command
        # included -- was reported as having succeeded silently, and a container
        # that refused one was recorded as having run it.
        if answer.get("error"):
            return 1, "", _message(answer["error"])
        result = answer.get("result") or {}
        return int(result.get("exit_code") or 0), _decoded(result.get("stdout")), _decoded(result.get("stderr"))
    finally:
        pool.release(lease)


def which(pool, image: str, names: list) -> Optional[dict]:
    """Where each of ``names`` resolves in the container for ``image``; None for no answer.

    What ``Environments`` is given to find the image's interpreter with, through
    the same pool as ``forward`` -- the service's ``which``, which runs nothing.
    """
    lease = pool.acquire(image)
    try:
        host, port = lease.endpoint.rsplit(":", 1)
        return RuntimeJsonRpcClient(host, int(port), token=lease.token).which(list(names))
    finally:
        pool.release(lease)


def execute(pool, environments, params: dict, timeout: Optional[float] = None) -> dict:
    """Run one command in the environment this service keeps for ``image``.

    The caller sends what it wants run and never learns where the environment
    is: this makes sure it exists, installs what the request says it needs, and
    prepends its interpreter. That is the whole difference from the ``docker``
    sandbox, where the client owns the environment because it can see the disk
    it is on.

    Everything about files is passed through untouched. The service inside the
    container already unpacks directories, rewrites the command's paths and
    packs the outputs back -- it does that for every container PartCAD runs --
    and a second implementation here would be a second place for it to be wrong.
    """
    image = params.get("image")
    if not image:
        raise ValueError("'image' is required: it is what decides which container runs this")
    command = params.get("command")
    if not command:
        raise ValueError("'command' is required")

    version = params.get("python_version")
    if not version:
        raise ValueError("'python_version' is required: it says which environment to run in")

    interpreter = environments.ensure(image, version, params.get("requirements") or [])

    lease = pool.acquire(image)
    try:
        host, port = lease.endpoint.rsplit(":", 1)
        rpc = RuntimeJsonRpcClient(host, int(port), token=lease.token)
        answer = rpc.execute(
            [interpreter] + list(command),
            {
                "stdin": params.get("stdin"),
                "cwd": params.get("cwd"),
                "input_files": params.get("input_files") or {},
                "output_files": params.get("output_files") or [],
                "input_dirs": params.get("input_dirs") or {},
                "output_dirs": params.get("output_dirs") or [],
                # Shared: any number of commands may run out of the environment
                # at once, and none while something installs into it.
                "lock": lock_for(version, exclusive=False),
            },
            timeout=timeout,
        )
        if not answer:
            raise RuntimeError(
                _lost(pool, lease, environments) or "The container serving '%s' returned no response" % image
            )
        if answer.get("error"):
            # Returned as this call's *result*, an error left the client
            # unwrapping a payload with no 'stdout' in it, so a command the
            # container refused arrived as a malformed answer.
            raise RuntimeError("%s: %s" % (image, _message(answer["error"])))
        # The container's payload, not its envelope. Two JSON-RPC layers are
        # already one more than the caller asked for; nesting a second envelope
        # inside the first would make the client unwrap twice to reach a field
        # it reads the same way it reads a local container's.
        return answer.get("result", answer)
    finally:
        pool.release(lease)
