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

from partcad import logging as pc_logging, wrapper
from partcad.part_factory.part_factory_file import PartFactoryFile
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import deserialize_response, serialize_request


sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from partcad.wrappers.ocp_serialize import register as register_ocp_helper

STEP = PartTypes.STEP

@register_factory(STEP.type)
class PartFactoryStep(PartFactoryFile):
    # lock = threading.Lock()
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action(f"Init{STEP.type.upper()}", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=f".{STEP.ext}", can_create=can_create)
            self._create(config)

            self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

    async def instantiate(self, part):
        await super().instantiate(part)
        with pc_logging.Action(f"{STEP.type.upper()}", part.project_name, part.name):
            wrapper_path = wrapper.get(f"{STEP.type}.py")
            request = {"build_parameters": {}}
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            response_serialized, errors = await self.runtime.run_async(
                [wrapper_path, os.path.abspath(part.path), os.path.abspath(self.project.config_dir)],
                request_serialized,
            )
            sys.stderr.write(errors)
            response = base64.b64decode(response_serialized)
            register_ocp_helper()
            result = pickle.loads(response)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])
            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1
            return shape
