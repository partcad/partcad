#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Running one of PartCAD's wrappers in the container a package declared (``container:``).

A Python sandbox can only bring what pip can install. A package whose script
needs more -- a native CAD kernel, a solver, a whole application -- names an
image instead, and PartCAD runs the script there, as the image has it: no
sandbox environment is built in it and nothing is installed into it. An output
implementation (``export:``, ``render:``, ``cae:``, ``cam:``) could always say
so (see `output.Implementation.container`); a ``partTypes:`` or ``sketchTypes:``
entry says it the same way (see 'partcad.type_wrapper'), and this module is the
half they share:

* `declaration` -- what a ``container:`` says, in either of its spellings;
* `cache_key` -- what a shape built in one is keyed on, in place of the
  sandbox's interpreter and requirements;
* `run_async` -- one wrapper run there, with the files it reads and writes made
  to reach it in both of the ways files reach a container (see below).

What runs in the container is the running PartCAD's own wrapper, sent with the
command rather than baked into the image (see `tools/containers/README.md`, "Why
the wrappers are mounted and not baked in"), and the wrapper runs the package's
script. A wrapper that hands back geometry hands it back as OCP shapes, so an
image a part or sketch type runs in has to carry OCP besides a ``python3``; the wrapper
says so in words when it cannot import it, rather than failing on the import.

Files reach the container two ways (``useDockerRemote``):

* ``mount`` -- the home and temporary directories, the context root and
  PartCAD's installation are bind-mounted at the paths they have here, and the
  command names files by those paths. Nothing has to be sent.
* ``upload`` -- nothing is mounted. Every directory the command line names is
  sent (by content, once per container: see `partcad_utils.container_files`),
  every argument naming something in one is rewritten to where it landed, and
  the directories the command writes into come back. The request is one opaque
  string and is not rewritten, which is why every path a wrapper reads from it
  has to be on its command line as well (`request_paths.carry`).
"""

import os
from typing import Optional

from . import sandbox_versions, shape_envelope
from .runtime_python_remote import input_dirs_for

# What the script is run with when the declaration says nothing: whatever the
# image's allowlist maps the name to, or its PATH finds (see
# PC_CONTAINER_ALLOWED_COMMANDS in tools/containers/README.md).
DEFAULT_COMMAND = "python"

# The keys a 'container:' mapping may have. 'port' was documented once and never
# read: PartCAD runs its own service in every container and reaches it on a port
# of its own choosing (see 'partcad_utils.containers').
KEYS = ("image", "name", "command")


def declaration(declared, who: str) -> Optional[dict]:
    """What a ``container:`` declares, as ``{"image", "name", "command"}``, or None where it declares nothing.

    The short form is the image and nothing else; the long form is a mapping
    with an ``image`` and, optionally, ``name`` -- what the container is for,
    the second word of its name (``partcad-plugin-<name>-...``) -- and
    ``command``, the name in the image's allowlist the wrapper is run with
    (``python`` by default).

    Raises:
        ValueError: it names no image, or is neither a string nor a mapping.
            'who' says whose declaration it was.
    """
    if not declared:
        return None
    if isinstance(declared, str):
        declared = {"image": declared}
    if not isinstance(declared, dict) or not isinstance(declared.get("image"), str) or not declared.get("image"):
        raise ValueError("%s declares a 'container:' that names no 'image:': %r" % (who, declared))
    for key in ("name", "command"):
        if key in declared and (not isinstance(declared[key], str) or not declared[key]):
            raise ValueError("%s declares a 'container:' whose '%s:' is not a name: %r" % (who, key, declared[key]))
    return dict(declared)


def command_of(container: dict) -> str:
    """The name the wrapper is run with in ``container``: its ``command``, or ``python``."""
    return container.get("command") or DEFAULT_COMMAND


def cache_key(container: dict) -> str:
    """What an object built in ``container`` is keyed on, in place of a sandbox's identity.

    The image as it was declared, and what it is run with. No interpreter
    version and no requirements: nothing is installed in the container, so
    what the script runs on is whatever the image carries, and the image's
    name is the only statement of that there is. Which is why an image a
    package names has to be pinned (a version or a digest, never ``latest``):
    a new build under the same name is not a new key, and shapes built with the
    old one are served for it.
    """
    return sandbox_versions.environment_cache_key("container", command_of(container), [], image=container["image"])


def upload_mode(runtime) -> bool:
    """Whether ``runtime``'s container is sent files rather than sharing them (``useDockerRemote``)."""
    from partcad_utils import containers

    spec = getattr(getattr(runtime, "endpoint", None), "spec", None)
    return getattr(spec, "mode", None) == containers.UPLOAD


async def run_async(ctx, container: dict, command: list, request: dict, written=()):
    """Run the wrapper ``command`` in ``container``, handed ``request``: ``(exit code, stdout, stderr)``.

    ``command`` is what a sandbox would be handed -- the wrapper's path first,
    then its arguments, then the request's paths behind
    `request_paths.ARGUMENT` -- and the name the image runs it with goes in
    front of it here. ``written`` are directories the command writes into that
    are to come back in ``upload`` mode, such as the package's ``cache_dir``:
    each is sent as a directory of its own, so the argument naming it is
    rewritten to a directory the service sends back, and created first, since a
    directory that is not there is not sent.

    The request is JSON (`shape_envelope.dumps`), and so is the answer: a
    container's output reaches PartCAD as text, and a frame of raw bytes does not
    survive that (see 'partcad_utils.containers.Endpoint.result').

    Raises:
        runtime.SandboxUnavailable: there is no container runtime here.
    """
    runtime = await ctx.get_container_runtime(container)
    written = [os.path.abspath(directory) for directory in written if directory]
    upload = upload_mode(runtime)
    if upload:
        for directory in written:
            os.makedirs(directory, exist_ok=True)
    # Every directory the command line names, whole: a wrapper imports its
    # siblings and so does a package's script. In 'mount' mode they are only
    # names, and cost nothing.
    input_dirs = input_dirs_for(command)
    for directory in written:
        if directory not in input_dirs:
            input_dirs.append(directory)
    extra = {"input_dirs": input_dirs}
    if upload and written:
        extra["output_dirs"] = written
    return await runtime.run_async([command_of(container)] + list(command), shape_envelope.dumps(request), **extra)
