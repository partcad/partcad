#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the Docker daemon has this process's directories, when it is not here.

Moved out of `partcad.runtime_python_docker` so that every container PartCAD
binds directories into asks it the same way -- the Python sandbox, KiCad, a
plugin's `container:`, and `pc ide open` starting an application, which runs in
a client that must not import the core. In a dev container holding the host's
Docker socket the daemon resolves a bind against the *host's* filesystem, so a
path from here binds an empty directory of the same name there, owned by root;
`mount_sources` is how a caller finds that out and where to bind from instead.
`partcad.runtime_python_docker` re-exports every name, which is still how the
sandbox and its tests reach them.
"""

import os
import platform
import re
import socket
import tempfile
import threading

from . import docker_mount
from . import logging as pc_logging


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


def mounts_are_shared(client, image: str, python: str = "python3") -> bool:
    """Whether the sandbox can bind PartCAD's directories into a container at all.

    True where the daemon shares this filesystem, and also where it does not
    but has each directory somewhere it can say -- see :func:`mount_sources`.
    """
    return mount_sources(client, image, python) is not False


def mount_sources(client, image: str, python: str = "python3"):
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

    if _probe_mounts(client, image, python=python):
        answer = None
    else:
        sources = _declared_sources()
        if sources is None:
            sources = _own_container_sources(client)
        answer = sources if sources and _probe_mounts(client, image, sources, python=python) else False
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


def _probe_mounts(client, image: str, sources=None, python: str = "python3") -> bool:
    """One throwaway container, asked whether it can see a file made here.

    ``python`` is what the image's interpreter is called: what the probe runs,
    since it is the one thing every image PartCAD starts is asked to carry.
    """
    import docker

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
                    python,
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
