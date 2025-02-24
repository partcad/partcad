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

from .part_factory_step import PartFactoryStep
from . import logging as pc_logging
from . import runtime
from .user_config import user_config

kicad_runtime_lock = threading.Lock()
kicad_runtime = None
kicad_runtime_uses_docker = False


async def get_runtime(ctx):
    global kicad_runtime, kicad_runtime_uses_docker, kicad_runtime_lock
    with kicad_runtime_lock:
        kicad_runtime = runtime.Runtime(ctx, "shell")
        kicad_runtime_uses_docker = user_config.use_docker_kicad
        if kicad_runtime_uses_docker:
            await kicad_runtime.use_docker(
                # TODO(clairbee): detect that this a build from a branch and prepend the branch name to the image tag
                "ghcr.io/partcad/partcad-container-kicad:" + sys.modules["partcad"].__version__,
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
            else:
                kicad_cli_path = shutil.which("kicad-cli")
                if kicad_cli_path is None:
                    raise Exception("KiCad executable is not found. Please, install KiCad first.")

            pc_logging.debug("Executing KiCad...")
            stdout, stderr = await kicad_runtime.run_async(
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

            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                part.error("KiCad failed to generate the STEP file. Please, check the PCB design.")
                return None
            pc_logging.debug("Finished executing KiCad")

            return await super().instantiate(part)
