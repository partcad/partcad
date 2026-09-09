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

import threading
from typing import Callable, Optional

# Where the volume is mounted inside every container this service starts. Fixed
# rather than configurable: the client never sees it, and a path the caller
# could choose would be a caller choosing where to write inside somebody else's
# container.
SANDBOX_ROOT = "/pc-sandbox"

# What the image's own interpreter is called *to the service inside it*. That
# service takes a command by the name its allowlist gives it, and the base image
# allows "python" (see `tools/containers/README.md`); "python3" is what the file
# is called, which is a different thing and is not allowed. The environment's
# own interpreter is a path rather than a name -- it did not exist when the
# image was built -- and the service recognises it by where it is.
IMAGE_PYTHON = "python"


def volume_name(image: str) -> str:
    """The volume holding the environments for one image.

    Per image, for the same reason a sandbox directory is: what pip resolves and
    what it compiles against depend on the native libraries underneath, and two
    images do not have the same ones.
    """
    import hashlib

    return "pc-sandbox-" + hashlib.sha256(image.encode()).hexdigest()[:12]


def environment_path(version: str) -> str:
    """Where the environment for one Python version lives inside the volume."""
    return "%s/v-env-%s" % (SANDBOX_ROOT, version)


def interpreter_path(version: str) -> str:
    """The interpreter to prepend to whatever the caller asked to run."""
    return "%s/bin/python" % environment_path(version)


class Environments:
    """The environments this service has built, and what is installed in them.

    ``run`` is how a command reaches the container -- the service passes
    something that forwards over JSON-RPC, and a test passes something that
    records. It must return ``(exit_code, stdout, stderr)``.
    """

    def __init__(self, run: Callable[[str, list], tuple]):
        self._run = run
        self._lock = threading.Lock()
        # (image, version) -> set of requirements already installed there.
        self._installed = {}
        self._built = set()
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

            with self._lock:
                known = self._installed.setdefault(key, set())
                wanted = [r for r in requirements if r not in known]

            for requirement in wanted:
                self._install(image, version, requirement)
                with self._lock:
                    self._installed[key].add(requirement)

        return interpreter_path(version)

    def _create(self, image: str, version: str) -> None:
        """Build the environment, if the volume does not already hold one.

        '--upgrade-deps' rather than a bare '-m venv': a fresh environment's
        bundled pip is as old as the image, and the first thing anybody does
        with this is install something.
        """
        exitcode, _, stderr = self._run(
            image, [IMAGE_PYTHON, "-m", "venv", "--upgrade-deps", environment_path(version)]
        )
        if exitcode != 0:
            raise RuntimeError(
                "Could not create the remote environment for Python %s in %s: %s"
                % (version, image, (stderr or "").strip() or "exit code %s" % exitcode)
            )

    def _install(self, image: str, version: str, requirement: str) -> None:
        exitcode, _, stderr = self._run(
            image,
            [interpreter_path(version), "-m", "pip", "install", "--no-input", requirement],
        )
        if exitcode != 0:
            raise RuntimeError(
                "Could not install '%s' into the remote environment for Python %s in %s: %s"
                % (requirement, version, image, (stderr or "").strip() or "exit code %s" % exitcode)
            )

    def forget(self, image: str) -> None:
        """Say the containers for this image are gone, so its environments are unknown.

        Not that they are *deleted* -- the volume outlives the container, which
        is the point of it. What is forgotten is only this service's belief
        about what is in there, so the next request re-checks rather than
        assuming a package is installed because a previous process installed it.
        """
        with self._lock:
            for key in [k for k in self._built if k[0] == image]:
                self._built.discard(key)
                self._installed.pop(key, None)
