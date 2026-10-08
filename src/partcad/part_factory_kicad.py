#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-16
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os
import platform
import shutil
import sys
import threading

from partcad_utils import container_image

from . import container_mounts
from . import logging as pc_logging
from . import runtime
from .part_factory_step import PartFactoryStep

# The image 'pc open --with kicad' runs as well (see '//builtin/open'): one KiCad
# container image in the product, not two.
KICAD_IMAGE = "ghcr.io/partcad/partcad-container-kicad"

kicad_runtime_lock = threading.Lock()
# Where a context keeps its KiCad runtime: one per context, made on the first
# board and reused for every one after it -- the cost of a container is in the
# starting, and asking the daemon again per board is that cost again.
_CONTEXT_ATTRIBUTE = "_partcad_kicad_runtime"


async def get_runtime(ctx):
    """The runtime ``kicad-cli`` runs in for ``ctx``, and whether it is a container: made once per context."""
    with kicad_runtime_lock:
        cached = getattr(ctx, _CONTEXT_ATTRIBUTE, None)
    if cached is not None:
        return cached

    uses_docker = ctx.user_config.use_docker_kicad
    made = runtime.Runtime(ctx, "shell")
    if uses_docker:
        # Asked before the client is built. Without it, a machine with no
        # container runtime got whatever 'docker.from_env()' raises on its
        # way to a socket that is not there -- "Error while fetching server
        # API version: ('Connection aborted.', FileNotFoundError(2, 'No
        # such file or directory'))" -- which names neither the PCB being
        # imported nor either of the two things the user can do about it.
        # 'pc render', 'pc export' and 'pc inspect' all arrive here, and all
        # three said that.
        #
        # 'SandboxUnavailable' rather than a plain exception because it
        # already means exactly this and is already handled as an answer
        # rather than a fault -- 'pc test' skips on it, the daemon reports
        # it to the IDE without a traceback (see
        # 'partcad_service_json_rpc.core.operations').
        #
        # 'docker_available' and not a check of its own: this has to agree
        # with what the sandbox and 'pc healthcheck' say about this machine.
        # 'use_docker_kicad' has already folded in 'useDocker', so only the
        # other half is left to ask.
        if not runtime.docker_available():
            raise runtime.SandboxUnavailable(
                "a KiCad PCB is imported by running 'kicad-cli' in a container, and no container "
                "runtime is available here. Start Docker, or install KiCad on this machine and set "
                "'useDockerKicad: false' so that PartCAD runs the 'kicad-cli' you installed."
            )
        # The release's image, unless CI is running the images built out of
        # this commit rather than the ones the release published; see
        # 'partcad_utils.container_image'.
        image = (
            container_image.image_name(KICAD_IMAGE)
            + ":"
            + container_image.image_tag(sys.modules["partcad"].__version__)
        )

        # The container is named after this image and everything else it is
        # started with, and replaced when it no longer matches -- see
        # 'partcad_utils.containers'. It used to be "integration-kicad",
        # whatever had made it, so an import for one release ran in a
        # container another release had started.
        def start():
            spec = container_mounts.spec_for(
                ctx,
                "kicad",
                image,
                "Importing a KiCad PCB",
                allowed_commands={"kicad-cli": "/usr/bin/kicad-cli"},
                # kicad-cli keeps its configuration under $HOME, and in
                # 'mount' mode on Linux it runs as this machine's user, whom
                # the image has no home directory for.
                environment={"HOME": "/tmp"},
            )
            return container_mounts.acquire(spec)

        # Off the event loop, and outside the lock: resolving, perhaps
        # pulling, creating and waiting for a container is seconds of
        # blocking calls, and every other part in the tree waits on this
        # loop meanwhile. Two boards racing here both ask, and get the one
        # container -- the name is the lock (see 'partcad_utils.containers').
        made.use_container(await asyncio.get_running_loop().run_in_executor(None, start))

    with kicad_runtime_lock:
        cached = getattr(ctx, _CONTEXT_ATTRIBUTE, None)
        if cached is None:
            cached = (made, uses_docker)
            setattr(ctx, _CONTEXT_ATTRIBUTE, cached)
    return cached


class PartFactoryKicad(PartFactoryStep):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitKicad", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=True,
            )
            # Complement the config object here if necessary

            # Take over the instantiate method from the STEP factory
            self.part.instantiate = self.instantiate

    async def instantiate(self, part):

        with pc_logging.Action("KiCad", part.project_name, part.name):
            kicad_pcb_path = part.path.replace(".step", ".kicad_pcb")

            if not os.path.exists(kicad_pcb_path) or os.path.getsize(kicad_pcb_path) == 0:
                pc_logging.error("KiCad PCB file is empty or does not exist: %s" % kicad_pcb_path)
                return None

            kicad_runtime, runtime_uses_docker = await get_runtime(self.ctx)
            pc_logging.debug(
                "Got a KiCad sandbox: %s (%s)" % (kicad_runtime.name, "docker" if runtime_uses_docker else "native")
            )
            if runtime_uses_docker:
                kicad_cli_path = "kicad-cli"
            elif platform.system() == "Darwin":
                kicad_cli_path = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
                if not os.path.exists(kicad_cli_path):
                    raise Exception("KiCad executable is not found. Please, install KiCad first.")
            else:
                kicad_cli_path = shutil.which("kicad-cli")
                if kicad_cli_path is None:
                    raise Exception("KiCad executable is not found. Please, install KiCad first.")

            pc_logging.debug("Executing KiCad...")
            exitcode, stdout, stderr = await kicad_runtime.run_async(
                [
                    kicad_cli_path,
                    "pcb",
                    "export",
                    "step",
                    "-o",
                    part.path,
                    kicad_pcb_path,
                ],
                # The board's whole directory rather than the board alone: a
                # board names its 3D models relative to the project
                # (${KIPRJMOD}), and in 'upload' mode a file that did not
                # travel is a model silently missing from the STEP. In 'mount'
                # mode these are paths the container already sees.
                input_dirs=[os.path.dirname(os.path.abspath(kicad_pcb_path))],
                output_files=[part.path],
            )

            if exitcode != 0 or not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                part.error("KiCad failed to generate the STEP file. Please, check the PCB design.")
                return None
            pc_logging.debug("Finished executing KiCad")

            return await super().instantiate(part)
