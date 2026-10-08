#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a container PartCAD starts for a context sees of this machine.

`partcad_utils.containers` starts every container and knows nothing of contexts.
This is the half that does: given a context and an image, it says which transfer
mode applies, and in `mount` mode which directories are bound and as whom -- the
same answer for the `docker` Python sandbox, KiCad and a plugin's `container:`,
because they are the same question. A copy per caller is how three callers come
to disagree about whether a dev container can mount anything at all.

The mount set is deliberately broad and deliberately the same for every
context: the home directory (which holds `~/.partcad` and, usually, the package
being worked on), the temporary directory, the state directory, the
installation, the context's root, and whatever the context asked for on top. A
set that does not vary is a container that never has to be replaced -- see
`runtime_python_docker.DockerPythonRuntime._mounted` for the long version.

Where the daemon cannot see this machine's files -- a dev container holding the
host's socket -- the mounts are taken from where the daemon keeps this
container's own (`runtime_python_docker.mount_sources`); where it cannot see
them at all, `mount` mode is refused with the setting that does work:
`useDockerRemote`, which sends the files instead.
"""

import os
import platform
import tempfile
from typing import Dict, Iterable, Optional

from partcad_utils import containers

from . import docker_mount, runtime


def standard_paths(ctx) -> list:
    """The host directories a container serving ``ctx`` is given in `mount` mode."""
    from .runtime_python_docker import INSTALL_DIR

    paths = []
    home = os.path.expanduser("~")
    # Not the filesystem root, which is what a broken or absent '~' expands to.
    if home and os.path.isdir(home) and home.rstrip("/\\"):
        paths.append(home)
    paths.append(tempfile.gettempdir())
    paths += [ctx.user_config.internal_state_dir, INSTALL_DIR]
    root = getattr(ctx, "root_path", None)
    if root:
        paths.append(root)
    paths += [p for p in getattr(ctx, "sandbox_paths", ()) or () if p]
    return paths


def host_user() -> Optional[str]:
    """This user, as the container should run in `mount` mode: Linux only.

    On Linux a bind mount passes uids straight through, so a container running
    as the image's user writes files this user cannot remove. Docker Desktop
    maps ownership itself, and naming a uid there that the image lacks breaks it.
    """
    if platform.system() == "Linux" and hasattr(os, "getuid"):
        return "%d:%d" % (os.getuid(), os.getgid())
    return None


def bind_mounts(client, image: str, paths: Iterable[str], what: str) -> Dict[str, Dict[str, str]]:
    """The binds for ``paths``, as the daemon behind ``client`` can make them.

    Raises `runtime.SandboxUnavailable` where it cannot make them at all, naming
    ``what`` needed them and the setting that works instead.
    """
    from . import runtime_python_docker as rpd

    paths = [p for p in paths if p]
    sources = rpd.mount_sources(client, image)
    if sources is False:
        raise runtime.SandboxUnavailable(
            "%s runs in a container, and the Docker daemon here cannot see this machine's files, so "
            "nothing can be mounted into it -- which is what a daemon on another machine, or behind "
            "DOCKER_HOST, looks like. Set 'useDockerRemote: true' (PC_USE_DOCKER_REMOTE=true) so that "
            "PartCAD sends the files with each command instead." % what
        )
    if sources is None:
        return docker_mount.mounts(paths)
    home = os.path.expanduser("~")
    missing = rpd.unbacked([p for p in paths if p != home], sources)
    if missing:
        raise runtime.SandboxUnavailable(
            "%s runs on a Docker daemon that does not share this filesystem, and binds from where it "
            "keeps this container's mounts -- but %s %s not on any of them. Mount %s into this container, "
            "name where the daemon has %s in PC_DOCKER_MOUNT_SOURCES, or set 'useDockerRemote: true' so "
            "that PartCAD sends the files instead."
            % (
                what,
                ", ".join(missing),
                "is" if len(missing) == 1 else "are",
                "it" if len(missing) == 1 else "them",
                "it" if len(missing) == 1 else "them",
            )
        )
    return rpd.client_mounts(sources)


def spec_for(
    ctx,
    role: str,
    image: str,
    what: str,
    allowed_commands: Optional[dict] = None,
    environment: Optional[dict] = None,
    volumes: Optional[dict] = None,
    sandbox_root: Optional[str] = None,
    extra_paths: Iterable[str] = (),
    client=None,
) -> containers.ContainerSpec:
    """The container serving ``ctx`` for ``role``, in this context's transfer mode."""
    mode = containers.transfer_mode(ctx.user_config)
    mounts = {}
    user = None
    if mode == containers.MOUNT:
        import docker

        client = client or docker.from_env()
        try:
            resolved, _ = containers.resolve_image(client, image)
        except containers.ContainerUnavailable as e:
            raise runtime.SandboxUnavailable(str(e))
        mounts = bind_mounts(client, resolved, standard_paths(ctx) + list(extra_paths), what)
        user = host_user()
    return containers.ContainerSpec(
        role=role,
        image=image,
        mode=mode,
        mounts=mounts,
        volumes=dict(volumes or {}),
        environment=dict(environment or {}),
        allowed_commands=dict(allowed_commands or {}),
        sandbox_root=sandbox_root,
        user=user,
    )


def acquire(spec: containers.ContainerSpec, client=None) -> containers.Endpoint:
    """`containers.acquire`, with a failure reported the way every sandbox reports one."""
    try:
        return containers.acquire(spec, client=client)
    except containers.ContainerUnavailable as e:
        raise runtime.SandboxUnavailable(str(e))
