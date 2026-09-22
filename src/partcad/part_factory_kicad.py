#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-16
#
# Licensed under Apache License, Version 2.0.
#

import os
import platform
import shutil
import sys
import threading

from partcad_utils import container_image

from . import logging as pc_logging
from . import runtime
from .part_factory_step import PartFactoryStep

kicad_runtime_lock = threading.Lock()
kicad_runtime = None
kicad_runtime_uses_docker = False


async def get_runtime(ctx):
    global kicad_runtime, kicad_runtime_uses_docker
    with kicad_runtime_lock:
        kicad_runtime = runtime.Runtime(ctx, "shell")
        kicad_runtime_uses_docker = ctx.user_config.use_docker_kicad
        if kicad_runtime_uses_docker:
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
            await kicad_runtime.use_docker(
                # The release, unless CI is running the images built out of
                # this commit rather than the ones the release published -- the
                # TODO that stood here asked for exactly that, and
                # 'partcad_utils.container_image' is where it ended up.
                container_image.image_name("ghcr.io/partcad/partcad-container-kicad")
                + ":"
                + container_image.image_tag(sys.modules["partcad"].__version__),
                "integration-kicad",
                5000,
                "localhost",
            )
        return kicad_runtime, kicad_runtime_uses_docker


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
                input_files=[kicad_pcb_path],
                output_files=[part.path],
            )

            if exitcode != 0 or not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                part.error("KiCad failed to generate the STEP file. Please, check the PCB design.")
                return None
            pc_logging.debug("Finished executing KiCad")

            return await super().instantiate(part)
