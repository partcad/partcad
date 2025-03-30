#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle
import sys
import threading

from . import logging as pc_logging
from . import wrapper
from .part_factory_file import PartFactoryFile
from . import telemetry

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


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
            register_ocp_helper()
            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{pickle.dumps}"):
                picklestring = pickle.dumps(request)
                request_serialized = base64.b64encode(picklestring).decode()

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{runtime.run_async}"):
                response_serialized, errors = await self.runtime.run_async(
                    [wrapper_path, os.path.abspath(part.path), os.path.abspath(self.project.config_dir)],
                    request_serialized,
                )
                sys.stderr.write(errors)

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{pickle.loads}"):
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])
            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1
            return shape
