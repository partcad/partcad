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
# the daemon it was asked of, the image it was asked in and the interpreter the
# probe ran there. Once per process: the answer is a property of how this
# machine reaches Docker, and that does not change while a command runs.
#
# The interpreter is in the key because "the image does not run here" can be
# about it rather than about the image ('ImageDoesNotRun'): an image with no
# 'python3' on its PATH may well have the interpreter another caller names, and
# that caller is owed a probe of its own rather than the first one's failure.
_MOUNTS_SHARED = {}
_MOUNTS_SHARED_GUARD = threading.Lock()

# What the probe writes and looks for. The name is only ever seen in a container
# that is about to be thrown away.
_PROBE_FILE = "partcad-mount-probe"

# What the probe exits with when it ran and the file was not there: the answer
# "this daemon has these directories somewhere else". Not 1, which is also what
# a container exits with when its image cannot run on this machine at all
# ("exec format error") and what the interpreter exits with on an error of its
# own - and those say nothing about where the daemon has anything.
_PROBE_ABSENT = 3

# What the daemon and an image call the same machine, where they call it
# differently: 'docker info' reports the kernel's name for it, an image the Go
# one. Anything not here is taken as it is spelt.
_ARCHITECTURES = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm", "i386": "386", "i686": "386"}


class ImageDoesNotRun(Exception):
    """The image the mount probe was asked in did not run here, so nothing was learnt about the mounts.

    Not the answer ``False`` is: that one is a container that ran and did not
    find the file, which says where the daemon has this machine's directories.
    This says only that the image does not start - most often because it has no
    build for this machine's platform - and a caller that reported it as a
    daemon unable to see this machine's files would send its reader to check
    'DOCKER_HOST' for a problem that is in the image.

    ``reason`` is why, as a clause - "it has no build for linux/arm64 (it is
    linux/amd64 only)" - for the caller to say in a sentence of its own.
    """

    def __init__(self, image: str, reason: str):
        super().__init__("%s does not run here: %s" % (image, reason))
        self.image = image
        self.reason = reason


def mounts_are_shared(client, image: str, python: str = "python3") -> bool:
    """Whether the sandbox can bind PartCAD's directories into a container at all.

    True where the daemon shares this filesystem, and also where it does not
    but has each directory somewhere it can say -- see :func:`mount_sources`.
    Raises :class:`ImageDoesNotRun` where ``image`` does not run here, which
    answers nothing about the mounts.
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

    And it raises :class:`ImageDoesNotRun` where the probe's container did not
    run at all, because then it found out nothing about where anything is: an
    image with no build for this machine's platform is not a daemon on another
    machine, and saying it was is how the reason got lost.

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
    key = (getattr(getattr(client, "api", None), "base_url", None), image, python)
    with _MOUNTS_SHARED_GUARD:
        if key in _MOUNTS_SHARED:
            return _answered(_MOUNTS_SHARED[key])

    try:
        answer = _probe_answer(client, image, key, python)
    except ImageDoesNotRun as e:
        # Remembered for this image, this daemon and this interpreter alone,
        # which is all it is about: another image on the same daemon, or the
        # same image asked to run another interpreter, is asked afresh and gets
        # the answer about the mounts that this one could not give.
        answer = e
    with _MOUNTS_SHARED_GUARD:
        _MOUNTS_SHARED[key] = answer
    return _answered(answer)


def _answered(answer):
    """'mount_sources''s answer as remembered: returned, or - an image that does not run - raised afresh."""
    if isinstance(answer, ImageDoesNotRun):
        raise ImageDoesNotRun(answer.image, answer.reason)
    return answer


def _probe_answer(client, image: str, key, python: str):
    """'mount_sources' without the cache."""
    if _probe_mounts(client, image, python=python):
        return None
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


def _probe_user():
    """Who the probe runs as: this user on Linux, and whoever the platform decides elsewhere (see '_probe_mounts')."""
    return ("%d:%d" % (os.getuid(), os.getgid())) if platform.system() == "Linux" else None


def _probe_mounts(client, image: str, sources=None, python: str = "python3") -> bool:
    """One throwaway container, asked whether it can see a file made here.

    ``python`` is what the image's interpreter is called: what the probe runs,
    since it is the one thing every image PartCAD starts is asked to carry.

    True when it found the file, and False when it ran and did not. A container
    that did not run at all has answered neither, and is told apart by asking
    the image to run once more with nothing mounted (see '_check_it_runs'):
    raises :class:`ImageDoesNotRun` where it will not run at all, and is False
    where it runs but would not take the mount - which is the daemon's answer
    after all.
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
                    "import os,sys; sys.exit(0 if os.path.isfile(%r) else %d)"
                    % (docker_mount.translate(marker), _PROBE_ABSENT),
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
                user=_probe_user(),
                remove=True,
            )
            return True
        except docker.errors.ContainerError as e:
            if e.exit_status == _PROBE_ABSENT:
                # It ran and did not find the file: the directory it was given
                # is not the one made above. This is the answer, not an error.
                return False
            failure = e
        except Exception as e:
            failure = e
    # Neither answer: the image did not run, or the daemon would not make the
    # mount. The two used to be one "cannot see this machine's files", and an
    # image with no build for this machine read as a 'DOCKER_HOST' somewhere
    # else. A container with nothing mounted tells them apart.
    _check_it_runs(client, image, python)
    pc_logging.debug("The 'docker' sandbox mount probe did not complete: %s" % failure)
    return False


def _check_it_runs(client, image: str, python: str) -> None:
    """Raise :class:`ImageDoesNotRun` unless ``image`` runs here with nothing mounted.

    Asked only after the probe failed in a way that was not its answer, so it
    costs a container only where something is already wrong.
    """
    try:
        client.containers.run(image, command=[python, "-c", "pass"], entrypoint=[], user=_probe_user(), remove=True)
    except Exception as e:
        raise ImageDoesNotRun(image, _why_it_does_not_run(client, image, e))


def _why_it_does_not_run(client, image: str, error) -> str:
    """Why ``image`` does not start here, as a clause: the platform where that is it, the error where not.

    The platform only where the error says it was the platform. An image built
    for another one runs where the daemon emulates it (binfmt and QEMU), and
    one that then fails for want of the interpreter asked for has a build that
    runs here and no interpreter: saying it had no build would send its reader
    after the wrong thing again. There the error is the reason, and the platform
    a fact beside it.
    """
    said = _error_text(error)
    platforms = _platforms(client, image)
    if platforms is not None and _is_platform_failure(said):
        here, built_for = platforms
        return "it has no build for %s (it is %s only)" % (here, built_for)
    lines = said.strip().splitlines()
    reason = "it does not start here: %s" % (lines[0] if lines else type(error).__name__)
    if platforms is not None:
        reason += " (it is a %s image, on a %s machine)" % (platforms[1], platforms[0])
    return reason


# How a daemon says a container failed because of its platform, in its own
# words and in Docker's CLI's: a binary for another machine, a manifest list
# with no entry for this one, an image pulled for another platform than the
# one asked for.
_PLATFORM_FAILURES = (
    "exec format error",
    "no matching manifest for",
    "does not match the detected host platform",
    "does not match the specified platform",
    "does not provide the specified platform",
)


def _error_text(error) -> str:
    """What ``error`` says, with what the container wrote to stderr when it ran far enough to write any."""
    said = str(error)
    stderr = getattr(error, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    if stderr and stderr not in said:
        said += "\n" + stderr
    return said


def _is_platform_failure(said: str) -> bool:
    lowered = said.lower()
    return any(marker in lowered for marker in _PLATFORM_FAILURES)


def _platform(os_name, architecture):
    """'<os>/<architecture>' in the image's spelling, or None if either is unknown."""
    if not os_name or not architecture:
        return None
    return "%s/%s" % (str(os_name).lower(), _ARCHITECTURES.get(str(architecture).lower(), str(architecture).lower()))


def _platforms(client, image: str):
    """(this daemon's platform, the image's) where they differ; None where they agree or cannot be told.

    The commonest reason an image does not start, and one its own error says
    badly: "exec format error" names neither platform. The image's is in what
    the daemon pulled, the daemon's in what it says about itself.
    """
    try:
        attrs = client.images.get(image).attrs or {}
        info = client.info() or {}
    except Exception:
        return None
    built_for = _platform(attrs.get("Os"), attrs.get("Architecture"))
    here = _platform(info.get("OSType"), info.get("Architecture"))
    if built_for is None or here is None or built_for == here:
        return None
    return here, built_for
