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
import subprocess
import tempfile
import threading

import build123d as b3d

from .part_factory_step import PartFactoryStep
from . import logging as pc_logging
from . import runtime_python_none
from .user_config import user_config

runtime_lock = threading.Lock()
runtime = None
runtime_uses_docker = False


def get_runtime(ctx):
    global runtime, runtime_uses_docker, runtime_lock
    with runtime_lock:
        runtime = runtime_python_none.NonePythonRuntime(ctx, ctx.python_version)
        runtime_uses_docker = user_config.use_docker_kicad
        if runtime_uses_docker:
            runtime.use_docker("partcad-integration-kicad", "integration-kicad", 5000, "localhost")
        return runtime, runtime_uses_docker


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

            # Take over the instantiate method from the Step factory
            # self.step_instantiate = self.part.instantiate
            self.part.instantiate = self.instantiate

            self.runtime_kicad = None

    async def instantiate(self, part):

        with pc_logging.Action("KiCad", part.project_name, part.name):
            kicad_pcb_path = part.path.replace(".step", ".kicad_pcb")

            if not os.path.exists(kicad_pcb_path) or os.path.getsize(kicad_pcb_path) == 0:
                pc_logging.error("KiCad PCB file is empty or does not exist: %s" % kicad_pcb_path)
                return None

            runtime, runtime_uses_docker = get_runtime(self.ctx)
            pc_logging.debug(
                "Got a KiCad sandbox: %s (%s)" % (runtime.name, "docker" if runtime_uses_docker else "native")
            )
            if runtime_uses_docker:
                kicad_cli_path = "kicad-cli"
            elif platform.system() == "Darwin":
                kicad_cli_path = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
            else:
                kicad_cli_path = shutil.which("kicad-cli")
                if kicad_cli_path is None:
                    raise Exception("KiCad executable is not found. Please, install KiCad first.")

            # TODO(clairbee): Add file upload to and download from the RPC server
            pc_logging.debug("Executing KiCad...")
            stdout, stderr = await runtime.run_async(
                [
                    kicad_cli_path,
                    "pcb",
                    "export",
                    "step",
                    "--no-virtual",
                    "-o",
                    part.path,
                    kicad_pcb_path,
                ],
            )

            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                part.error("KiCad failed to generate the STEP file. Please, check the PCB design.")
                return None
            pc_logging.debug("Finished executing KiCad")

            await super().instantiate(part)
            # return await self.step_instantiate(part)
