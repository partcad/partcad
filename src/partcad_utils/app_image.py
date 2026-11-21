#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD image, `ghcr.io/partcad/partcad`: whether this process runs in it, and how to run it.

The image is PartCAD itself, published for whoever would rather `docker run` it
than install it (`tools/containers/partcad/Dockerfile`). Three things behave
differently inside it, and each asks here rather than looking for a file or a
hostname of its own:

* `pc upgrade` refuses, because a newer PartCAD is a newer image
  (`partcad_client.selfupdate`);
* `pc init` writes the MCP server into an agent's configuration as
  `docker run ... ghcr.io/partcad/partcad mcp` rather than `pc mcp`, because the
  machine the agent runs on has no `pc` (`partcad.ai_agents`);
* `pc healthcheck` says how to give the container the host's Docker, rather
  than how to install Docker (`partcad.healthcheck.docker_available`).

Read out of the environment the image sets, and nothing else: the image is the
one thing that knows it is the image. The tests set the same variable.
"""

import os

# What the image sets on everything that runs in it -- the variable the editor
# extension sets for the bundle it owns, with a value of its own.
MANAGED_BY_ENV = "PARTCAD_MANAGED_BY"
MANAGED_BY_IMAGE = "docker-image"

# The reference the image was published as, without a tag: what to `docker run`
# and what to `docker pull`.
IMAGE_ENV = "PARTCAD_IMAGE"
DEFAULT_IMAGE = "ghcr.io/partcad/partcad"

# Where the image keeps PartCAD's state, and the volume every documented way of
# running it mounts there. Without it every run provisions a CAD sandbox from
# nothing, which takes minutes -- longer than an MCP client waits for a tool.
STATE_DIR = "/home/pc/.partcad"
STATE_VOLUME = "partcad-home"

# The host's Docker socket, as the image is given it.
DOCKER_SOCKET = "/var/run/docker.sock"


def running_in_image() -> bool:
    """Whether this process runs in the PartCAD image."""
    return os.environ.get(MANAGED_BY_ENV) == MANAGED_BY_IMAGE


def image() -> str:
    """The image to run and to pull, without a tag: the one this process runs in, or the published one."""
    return (os.environ.get(IMAGE_ENV) or "").strip() or DEFAULT_IMAGE


def docker_run_args(workspace: str, *args: str, socket: bool = False, image_ref: str = "") -> list:
    """The arguments to `docker` that run PartCAD on ``workspace``, then ``args``.

    ``workspace`` is mounted at the path it has on the host, and is the working
    directory, so that a path PartCAD prints -- in a log, in an MCP result, in a
    file it writes -- is the path the reader on the host would use. The state
    volume keeps the sandboxes between runs. ``-i`` because an MCP client
    speaks to the server on standard input; ``--rm`` because every run is a
    fresh container and the volume is what is kept.

    ``socket`` mounts the host's Docker socket, which is what lets PartCAD start
    containers of its own -- KiCad, plugins, the `docker` sandbox -- and which
    hands the container control of the host's Docker. Off unless asked for.
    """
    run = ["run", "-i", "--rm", "-v", "%s:%s" % (STATE_VOLUME, STATE_DIR)]
    run += ["-v", "%s:%s" % (workspace, workspace), "-w", workspace]
    if socket:
        run += ["-v", "%s:%s" % (DOCKER_SOCKET, DOCKER_SOCKET)]
    return run + [image_ref or image(), *args]
