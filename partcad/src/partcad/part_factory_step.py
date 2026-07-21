#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os
import sys
import threading

from . import logging as pc_logging
from . import wrapper
from .part_factory_file import PartFactoryFile
from . import telemetry

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
import ocp_wire


@telemetry.instrument()
class PartFactoryStep(PartFactoryFile):
    lock = threading.Lock()

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitSTEP", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".step", can_create=can_create)
            self._create(config)

            self.runtime = self.ctx.get_python_runtime("3.11")

    async def instantiate(self, part):
        await super().instantiate(part)
        with pc_logging.Action("STEP", part.project_name, part.name):
            wrapper_path = wrapper.get("step.py")
            request = {"build_parameters": {}}
            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{ocp_wire.serialize}"):
                request_serialized = ocp_wire.serialize(request)

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{runtime.run_async}"):
                command = [wrapper_path, os.path.abspath(part.path), os.path.abspath(self.project.config_dir)]
                exitcode, response_serialized, errors = await self.runtime.run_async(
                    command,
                    request_serialized,
                )
                if exitcode != 0 and len(errors) == 0:
                    errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{ocp_wire.deserialize}"):
                result = ocp_wire.deserialize(response_serialized)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])
            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1
            return shape
