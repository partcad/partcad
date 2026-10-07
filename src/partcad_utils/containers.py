#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every container PartCAD starts: how it is named, started, reused, and given files.

There used to be five ways, one per thing that needed a container -- the `docker`
Python sandbox, KiCad, a plugin's `container:`, `pc open`, and the
`partcad-service-remote-docker` pool -- and they disagreed about everything that
matters. One named its container after a constant and reused whatever answered
to it, so a machine ran KiCad imports for 0.8.158 in a container 0.8.129 had
made; one labelled its containers and another did not, so `pc system prune`
could clean up after the first and never the second; one reached its container
on a bridge IP that does not route on macOS. This is the one way now.

**A container is described, not named.** A caller says what it needs -- a
`ContainerSpec`: the image, how files reach it, which commands may run -- and
the name is derived from that description: ``partcad-<role>-<tag>-<identity>``.
The identity is a digest of everything fixed at creation, the version of the
service running inside included, so two callers needing the same container
share it and two needing different ones never touch each other's. The digest is
also a label, and a container that answers to the name but carries another
digest, or runs an image other than the one its tag resolves to now, is
replaced rather than trusted.

**Every container runs the same service.** `partcad_utils.container_service` is
copied into the container after it is created and before it starts, and is its
command. So the protocol a caller speaks is the one shipped with that caller,
whatever image it runs in and whatever copy that image happens to carry -- the
mismatch that left a KiCad image rejecting `input_dirs` cannot recur. The cost is
a `python3` on the image's PATH, which every image PartCAD uses has.

**Files reach it one of two ways,** chosen by `transfer_mode()`:

* ``mount`` -- directories are bind-mounted at the paths they have here, and a
  command names files by those paths. Nothing travels with a request. This
  needs the daemon to see this machine's filesystem.
* ``upload`` -- nothing is mounted from here. The files a command reads travel
  with the request and the files it writes come back with the answer, through
  the service's `input_files`/`input_dirs`/`output_files`/`output_dirs`. This is
  what `useDockerRemote` asks for: a daemon on another machine, which can see
  none of this one's files.

A caller does not have to know which: `Endpoint.run()` takes the same arguments
either way and does what the mode requires with them.
"""

import base64
import functools
import hashlib
import io
import json
import os
import re
import secrets
import tarfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import __version__, container_service, docker_image
from . import logging as pc_logging
from .json_rpc_client import RuntimeJsonRpcClient

MOUNT = "mount"
UPLOAD = "upload"

# Every container PartCAD starts carries this, which is how `pc system prune`
# tells PartCAD's containers from everybody else's (see `partcad.docker_prune`).
LABEL_CONTAINER = "partcad.container"
LABEL_VERSION = "partcad.version"
LABEL_ROLE = "partcad.role"
LABEL_IDENTITY = "partcad.identity"
LABEL_MODE = "partcad.mode"

# Where the service is put inside every container. At the root rather than under
# /tmp or /opt: the root exists in every image, and /tmp is sometimes a mount.
SERVICE_DIR = "/.partcad-service"
SERVICE_PATH = SERVICE_DIR + "/container_service.py"
SERVICE_PORT = container_service.DEFAULT_PORT

# How long a container may take, once started, before its service answers. The
# service is a stdlib HTTP server and is listening in well under a second; this
# is for a cold daemon and a slow disk.
READY_SECONDS = 60.0

# How many times a start is attempted when another process is starting the same
# container at the same moment. Each attempt either wins, finds the other's
# container, or loses a removal race and goes round again.
START_ATTEMPTS = 3


class ContainerUnavailable(Exception):
    """A container that was needed could not be had: no image, no start, no answer."""


def transfer_mode(config=None) -> str:
    """`upload` where `useDockerRemote` says the daemon cannot see this machine's files, else `mount`."""
    if config is None:
        from .user_config import user_config as config
    return UPLOAD if getattr(config, "use_docker_remote", False) else MOUNT


@dataclass(frozen=True)
class ContainerSpec:
    """What a container has to be. Everything here is fixed when it is created.

    Anything that varies per command -- the command, its standard input, the
    display a window should open on -- is not here, but in `Endpoint.run()`.
    """

    # What the container is for, as the second word of its name: `sandbox`,
    # `kicad`, `plugin-<name>`, `open-<tool>`. Not part of the identity: two
    # roles needing exactly the same container may share it.
    role: str
    image: str
    mode: str = MOUNT
    # {host directory: {"bind": path in the container, "mode": "rw" | "ro"}}, as
    # the Docker SDK wants them. Ignored in `upload` mode, where nothing from
    # here is visible -- which is the point of that mode.
    mounts: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # {named volume: {"bind": ..., "mode": ...}}. Kept in both modes: a volume is
    # the daemon's own storage, not this machine's.
    volumes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    # What may run, by name: an absolute path, or None for "look it up on the
    # container's PATH". Merged over whatever the image itself allows.
    allowed_commands: Dict[str, Optional[str]] = field(default_factory=dict)
    # Where environments built inside the container live, for a sandbox whose
    # interpreters cannot be named in advance. See `container_service`.
    sandbox_root: Optional[str] = None
    # "uid:gid" to run as. In `mount` mode on Linux this is the host's own, so
    # that what the container writes into a mount stays usable outside it.
    user: Optional[str] = None
    # The interpreter the service is started with.
    service_python: str = "python3"

    def mounted(self) -> Dict[str, Dict[str, str]]:
        return dict(self.mounts) if self.mode == MOUNT else {}


def _service_path() -> str:
    """Where the service's source is, as a file that can be copied into a container.

    Beside the module, as a `.py`. A frozen bundle compiles modules into an
    archive and gives them a `__file__` naming a `.pyc` that is not on disk, so
    the bundle ships the source as data (see dev-tools/pyinstaller/partcad.spec)
    and this looks for it under the name it would have had.
    """
    path = container_service.__file__
    if not path.endswith(".py"):
        path = os.path.splitext(path)[0] + ".py"
    return path


@functools.lru_cache(maxsize=1)
def _service_source() -> bytes:
    """The service, as the bytes put into every container. Read once: every name derivation hashes it."""
    path = _service_path()
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise ContainerUnavailable(
            "PartCAD's container service is not where this installation should have it (%s): %s" % (path, e)
        )


def identity(spec: ContainerSpec) -> str:
    """A digest of everything that makes one container different from another.

    The service's own source is in it: the container runs that file, so a
    PartCAD shipping a different one needs a different container, and gets one
    under a different name rather than reusing a container whose service speaks
    an older dialect.
    """
    mounted = spec.mounted()
    described = {
        "image": spec.image,
        "mode": spec.mode,
        "mounts": sorted((source, value["bind"], value.get("mode", "rw")) for source, value in mounted.items()),
        "volumes": sorted((name, value["bind"], value.get("mode", "rw")) for name, value in spec.volumes.items()),
        "environment": sorted(spec.environment.items()),
        "allowed": sorted((name, path or "") for name, path in spec.allowed_commands.items()),
        "sandbox_root": spec.sandbox_root or "",
        "user": spec.user or "",
        "service_python": spec.service_python,
        "service": hashlib.sha256(_service_source()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(described, sort_keys=True).encode("utf-8")).hexdigest()


_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _tag_of(image: str) -> str:
    """The tag of an image reference -- the release, for PartCAD's own -- or "latest"."""
    if "@" in image:
        return "digest"
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else "latest"


def container_name(spec: ContainerSpec) -> str:
    """``partcad-<role>-<tag>-<identity>``: whose it is, which version, and exactly which.

    The tag is there for a person reading `docker ps`, who wants to see that the
    KiCad container is 0.8.160's; the identity is there for PartCAD, which needs
    every difference that matters to make a different name.
    """
    role = _UNSAFE.sub("-", spec.role).strip("-.") or "container"
    tag = _UNSAFE.sub("-", _tag_of(spec.image)).strip("-.")[:32] or "latest"
    return "partcad-%s-%s-%s" % (role, tag, identity(spec)[:12])


# --------------------------------------------------------------------------- #
# The image                                                                     #
# --------------------------------------------------------------------------- #


def resolve_image(client, image: str):
    """The image to run, pulled if this machine does not have it: (reference, image object).

    The architecture-suffixed tag first and the bare one second (see
    `docker_image.candidates`), local before remote, so an image built by hand
    for testing is used the way a pulled one is.
    """
    import docker

    names = docker_image.candidates(image)
    for name in names:
        try:
            return name, client.images.get(name)
        except docker.errors.ImageNotFound:
            continue
    errors = []
    for name in names:
        try:
            return name, client.images.pull(name)
        except Exception as e:
            errors.append("%s: %s" % (name, e))
    raise ContainerUnavailable("Cannot get an image for '%s': %s" % (image, "; ".join(errors)))


def _env_list_to_dict(entries) -> Dict[str, str]:
    result = {}
    for entry in entries or ():
        key, sep, value = str(entry).partition("=")
        if sep:
            result[key] = value
    return result


def _image_allowlist(image_obj) -> Dict[str, Optional[str]]:
    """What the image itself says may run, from the environment it was built with."""
    env = _env_list_to_dict(((getattr(image_obj, "attrs", None) or {}).get("Config") or {}).get("Env"))
    raw = env.get("PC_CONTAINER_ALLOWED_COMMANDS", "")
    try:
        return {str(k): (None if v is None else str(v)) for k, v in json.loads(raw).items()} if raw.strip() else {}
    except ValueError:
        return {}


# --------------------------------------------------------------------------- #
# Where the daemon is, and how to reach a container on it                      #
# --------------------------------------------------------------------------- #

_LOCAL_SCHEMES = ("unix", "npipe", "http+docker")


def daemon_host(client) -> Optional[str]:
    """The host the daemon runs on, when it is not this machine; None when it is.

    Read from the client's base URL: a socket or a named pipe is this machine,
    and so is a TCP address on loopback. Anything else is somewhere a published
    port has to be dialled at.
    """
    api = getattr(client, "api", None)
    base = str(getattr(api, "base_url", "") or "")
    scheme, _, rest = base.partition("://")
    if scheme == "http+docker" and rest.startswith("ssh"):
        # docker-py talks to an `ssh://` daemon through an adapter and keeps
        # the real address there, behind a base URL that names no host at all.
        target = str(getattr(getattr(api, "_custom_adapter", None), "ssh_host", "") or "")
        scheme, _, rest = ("ssh", "", target.partition("://")[2] or target)
        if not rest:
            return None
    elif not rest or scheme in _LOCAL_SCHEMES:
        return None
    host = rest.split("/", 1)[0]
    host = host.rsplit("@", 1)[-1]
    if host.startswith("["):
        host = host[1 : host.find("]")]
    else:
        host = host.rsplit(":", 1)[0]
    if host in ("localhost", "127.0.0.1", "::1", ""):
        return None
    return host


def _candidates(container, remote_host: Optional[str]) -> List[Tuple[str, int]]:
    """Every (host, port) the container's service might be reached at, most likely first.

    The published port first, which is how Docker Desktop on macOS and Windows,
    and a daemon on another machine, can be reached at all. The container's own
    address on its network second, which is what reaches it from a dev container
    on the same daemon: a port the host published on its loopback is not on the
    dev container's.
    """
    found = []
    settings = (getattr(container, "attrs", None) or {}).get("NetworkSettings") or {}
    for binding in (settings.get("Ports") or {}).get("%d/tcp" % SERVICE_PORT) or ():
        host_ip = binding.get("HostIp") or ""
        port = binding.get("HostPort")
        if not port:
            continue
        if remote_host is not None:
            found.append((remote_host, int(port)))
        elif host_ip in ("", "0.0.0.0", "::", "[::]"):
            found.append(("127.0.0.1", int(port)))
        else:
            found.append((host_ip, int(port)))
    if remote_host is None:
        for network in (settings.get("Networks") or {}).values():
            address = (network or {}).get("IPAddress")
            if address:
                found.append((address, SERVICE_PORT))
    seen = set()
    return [c for c in found if not (c in seen or seen.add(c))]


@dataclass
class Endpoint:
    """A running container and how to talk to its service."""

    name: str
    spec: ContainerSpec
    container: object
    host: str
    port: int
    token: Optional[str]

    def client(self) -> RuntimeJsonRpcClient:
        return RuntimeJsonRpcClient(self.host, self.port, token=self.token)

    # ------------------------------------------------------------- running --

    def params(
        self,
        stdin: Optional[str] = None,
        cwd: Optional[str] = None,
        input_files=None,
        output_files=None,
        input_dirs=None,
        output_dirs=None,
    ) -> dict:
        """The request parameters for one command, as this container's transfer mode needs them.

        In ``mount`` mode the paths are the files: they exist in the container
        at the paths they have here, so nothing is sent but their names. In
        ``upload`` mode every file a command reads is sent and every file it
        writes is named, so that it can be sent back.
        """
        params = {
            "stdin": base64.b64encode(stdin.encode("utf-8")).decode("utf-8") if stdin else None,
            "cwd": cwd,
        }
        if self.spec.mode != UPLOAD:
            return params
        files = {}
        for path in input_files or ():
            with open(path, "rb") as f:
                files[path] = base64.b64encode(f.read()).decode("utf-8")
        params["input_files"] = files
        params["input_dirs"] = {path: container_service.pack_directory(path) for path in input_dirs or ()}
        params["output_files"] = list(output_files or ())
        params["output_dirs"] = list(output_dirs or ())
        return params

    def result(self, response, output_files=None, output_dirs=None) -> Tuple[int, str, str]:
        """What a command answered, as (exit code, stdout, stderr), with its files put back here.

        Only the files the caller named are written: a server that sends back
        something nobody asked for does not get to write it anywhere. A
        directory is written over, not mirrored -- a file the command deleted is
        left in place here rather than deleted, because a command that misbehaves
        should cost a stale file and not somebody's work.
        """
        if not response:
            return 1, "", "The '%s' container returned no response" % self.name
        if response.get("error"):
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            data = error.get("data") if isinstance(error, dict) else None
            if isinstance(data, dict) and data.get("message"):
                message = "%s: %s" % (message, data["message"])
            return 1, "", "The '%s' container refused the command: %s" % (self.name, message)
        if "result" not in response:
            return 1, "", "The '%s' container answered without a result: %s" % (self.name, response)
        result = response["result"]
        stdout = base64.b64decode(result.get("stdout") or b"").decode("utf-8", errors="replace")
        stderr = base64.b64decode(result.get("stderr") or b"").decode("utf-8", errors="replace")
        if self.spec.mode == UPLOAD:
            wanted = set(output_files or ())
            for name, payload in (result.get("output_files") or {}).items():
                if name in wanted:
                    with open(name, "wb") as f:
                        f.write(base64.b64decode(payload))
                else:
                    pc_logging.error("The '%s' container sent a file nobody asked for: %s" % (self.name, name))
            wanted_dirs = set(output_dirs or ())
            for name, archive in (result.get("output_dirs") or {}).items():
                if name in wanted_dirs:
                    os.makedirs(name, exist_ok=True)
                    container_service.unpack_directory(archive, name)
                else:
                    pc_logging.error("The '%s' container sent a directory nobody asked for: %s" % (self.name, name))
        code = result.get("exit_code")
        return (int(bool(stderr)) if code is None else int(code)), stdout, stderr

    def run(
        self,
        command: List[str],
        stdin: Optional[str] = None,
        cwd: Optional[str] = None,
        input_files=None,
        output_files=None,
        input_dirs=None,
        output_dirs=None,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, str]:
        params = self.params(stdin, cwd, input_files, output_files, input_dirs, output_dirs)
        response = self.client().execute(list(command), params, timeout=timeout)
        return self.result(response, output_files, output_dirs)

    async def run_async(
        self,
        command: List[str],
        stdin: Optional[str] = None,
        cwd: Optional[str] = None,
        input_files=None,
        output_files=None,
        input_dirs=None,
        output_dirs=None,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, str]:
        params = self.params(stdin, cwd, input_files, output_files, input_dirs, output_dirs)
        response = await self.client().execute_async(list(command), params, timeout=timeout)
        return self.result(response, output_files, output_dirs)


# --------------------------------------------------------------------------- #
# Starting one                                                                  #
# --------------------------------------------------------------------------- #

_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


def _service_archive() -> bytes:
    """The service as a tar `put_archive` can unpack at the container's root."""
    buffer = io.BytesIO()
    source = _service_source()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        directory = tarfile.TarInfo(SERVICE_DIR.lstrip("/"))
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)
        info = tarfile.TarInfo(SERVICE_PATH.lstrip("/"))
        info.size = len(source)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(source))
    return buffer.getvalue()


def _token_of(container) -> Optional[str]:
    env = _env_list_to_dict(((getattr(container, "attrs", None) or {}).get("Config") or {}).get("Env"))
    return env.get("PC_CONTAINER_TOKEN") or None


def _fits(container, digest: str, image_obj) -> Optional[str]:
    """Why ``container`` is not the one wanted, or None if it is."""
    labels = (
        ((getattr(container, "attrs", None) or {}).get("Config") or {}).get("Labels")
        or getattr(container, "labels", None)
        or {}
    )
    if labels.get(LABEL_IDENTITY) != digest:
        return "it was created for something else (identity %s)" % (labels.get(LABEL_IDENTITY) or "none")
    wanted = getattr(image_obj, "id", None)
    running = (getattr(container, "attrs", None) or {}).get("Image")
    if wanted and running and wanted != running:
        return "it runs %s and the image is now %s" % (running[:19], wanted[:19])
    if getattr(container, "status", "") in ("dead", "removing"):
        return "it is %s" % container.status
    return None


def _logs(container) -> str:
    try:
        return container.logs(tail=30).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _wait_ready(container, remote_host, deadline: float, ping: Callable[[str, int], Optional[int]]):
    """The (host, port) the container's service answers on, once it does."""
    while True:
        try:
            container.reload()
        except Exception:
            pass
        status = getattr(container, "status", "")
        if status in ("exited", "dead"):
            raise ContainerUnavailable("the container stopped before its service answered")
        for host, port in _candidates(container, remote_host):
            if ping(host, port) is not None:
                return host, port
        if time.monotonic() > deadline:
            raise ContainerUnavailable("its service did not answer within %d seconds" % READY_SECONDS)
        time.sleep(0.25)


def _default_ping(host: str, port: int) -> Optional[int]:
    return RuntimeJsonRpcClient(host, port).ping(timeout=1.0)


def acquire(spec: ContainerSpec, client=None, ping: Callable[[str, int], Optional[int]] = None) -> Endpoint:
    """The running container for ``spec``: found, verified, or created; and ready.

    Safe to call from many threads and many processes at once. Within a process
    a lock per name serialises the work; between processes the name is the
    lock -- Docker refuses a second container of one name, and whoever loses
    goes round and finds the winner's.
    """
    import docker

    if client is None:
        client = docker.from_env()
    ping = ping or _default_ping
    name = container_name(spec)
    digest = identity(spec)
    remote_host = daemon_host(client)

    with _lock(name):
        reference, image_obj = resolve_image(client, spec.image)
        last_error = None
        for _ in range(START_ATTEMPTS):
            try:
                container = client.containers.get(name)
            except docker.errors.NotFound:
                container = None

            if container is not None:
                why = _fits(container, digest, image_obj)
                if why is not None:
                    pc_logging.info("Replacing the '%s' container: %s" % (name, why))
                    try:
                        container.remove(force=True)
                    except docker.errors.NotFound:
                        pass
                    except docker.errors.APIError as e:
                        if getattr(e, "status_code", None) != 409:
                            raise
                        time.sleep(0.5)  # another process is removing it
                    continue
                return _start_and_wait(name, spec, container, remote_host, ping)

            try:
                container = _create(client, name, spec, digest, reference, image_obj, remote_host)
            except docker.errors.APIError as e:
                if getattr(e, "status_code", None) == 409:
                    # Created by somebody else in the meantime. The daemon
                    # reserves a name before the container behind it can be
                    # inspected, so looking straight away finds nothing; wait
                    # for it to be there before going round.
                    last_error = e
                    _await_named(client, name)
                    continue
                raise ContainerUnavailable("Cannot create the '%s' container from %s: %s" % (name, reference, e))
            return _start_and_wait(name, spec, container, remote_host, ping, created_here=True)
        raise ContainerUnavailable("Cannot start the '%s' container: %s" % (name, last_error or "it kept changing"))


def _await_named(client, name: str, seconds: float = 10.0) -> None:
    """Wait for a container whose name the daemon has reserved to become inspectable."""
    import docker

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            client.containers.get(name)
            return
        except docker.errors.NotFound:
            time.sleep(0.1)


def _create(client, name, spec, digest, reference, image_obj, remote_host):
    # The image's own list, then the spec's on top -- except that a name the
    # spec allows only "wherever PATH finds it" does not unpin a path the image
    # chose for it. A plugin saying "my implementations run on python" means
    # the image's python, not whichever one PATH happens to find first.
    allowed = dict(_image_allowlist(image_obj))
    for command, path in spec.allowed_commands.items():
        if path is not None or command not in allowed:
            allowed[command] = path
    environment = dict(spec.environment)
    environment["PC_CONTAINER_ALLOWED_COMMANDS"] = json.dumps(allowed, sort_keys=True)
    environment["PC_CONTAINER_TOKEN"] = secrets.token_hex(24)
    environment["PC_CONTAINER_PORT"] = str(SERVICE_PORT)
    if spec.sandbox_root:
        environment["PC_CONTAINER_SANDBOX_ROOT"] = spec.sandbox_root
    volumes = dict(spec.mounted())
    volumes.update(spec.volumes)
    labels = {
        LABEL_CONTAINER: "1",
        LABEL_VERSION: __version__,
        LABEL_ROLE: spec.role,
        LABEL_IDENTITY: digest,
        LABEL_MODE: spec.mode,
    }
    with pc_logging.Action("Container", spec.role, name):
        container = client.containers.create(
            reference,
            name=name,
            command=[spec.service_python, SERVICE_PATH],
            entrypoint=[],
            environment=environment,
            labels=labels,
            volumes=volumes or None,
            user=spec.user,
            # Loopback when the daemon is this machine, so the service is
            # reachable from here and from nowhere else; every interface when
            # it is another machine, since that is the only way to reach it --
            # and the token is what stands between it and the network.
            ports={"%d/tcp" % SERVICE_PORT: ("0.0.0.0" if remote_host else "127.0.0.1", None)},
            detach=True,
        )
        # Before the first start, so the command exists when it runs. A
        # created container accepts an archive the same as a running one.
        container.put_archive("/", _service_archive())
    return container


def _start_and_wait(name, spec, container, remote_host, ping, created_here=False) -> Endpoint:
    import docker

    status = getattr(container, "status", "")
    if status != "running":
        if status == "created" and not created_here:
            # Somebody else's, between its create and its start. The service
            # may not be in it yet; putting it there again is harmless.
            container.put_archive("/", _service_archive())
        try:
            container.start()
        except docker.errors.APIError as e:
            if getattr(e, "status_code", None) not in (304, 409):
                raise ContainerUnavailable("Cannot start the '%s' container: %s" % (name, e))
    try:
        host, port = _wait_ready(container, remote_host, time.monotonic() + READY_SECONDS, ping)
    except ContainerUnavailable as e:
        logs = _logs(container)
        if created_here:
            try:
                container.remove(force=True)
            except Exception:
                pass
        hint = ""
        if "No such file" in logs or "not found" in logs:
            hint = (
                "\nThe image may have no '%s' on its PATH; the service PartCAD runs in every container needs one."
                % spec.service_python
            )
        raise ContainerUnavailable(
            "The '%s' container (%s) is not usable: %s.%s%s"
            % (name, spec.image, e, ("\n" + logs) if logs else "", hint)
        )
    _open_volumes(name, spec, container)
    return Endpoint(name=name, spec=spec, container=container, host=host, port=port, token=_token_of(container))


def _open_volumes(name: str, spec: ContainerSpec, container) -> None:
    """Make every named volume writable by whoever the service runs as.

    Docker creates a volume's mount point as root, mode 0755, when the image has
    no directory there to copy -- and the service runs as the image's user or
    as this machine's, never as root. So a sandbox environment built in a fresh
    volume failed with "Permission denied" on its very first file, which is how
    the remote sandbox behaved on every new machine. Sticky, like /tmp, so that
    one user cannot remove another's environment.

    Done as root, every time the container is acquired rather than only when
    it is created: a container made by a release without this kept failing
    otherwise, and one `chmod` per process per container is nothing.
    """
    for volume in spec.volumes.values():
        try:
            code, output = container.exec_run(["chmod", "1777", volume["bind"]], user="0")
        except Exception as e:
            code, output = 1, str(e).encode("utf-8")
        if code:
            pc_logging.warning(
                "Could not make %s writable in the '%s' container: %s"
                % (volume["bind"], name, (output or b"").decode("utf-8", errors="replace").strip())
            )
