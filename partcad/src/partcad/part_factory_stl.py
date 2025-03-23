#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import os
import base64
import pickle
import sys

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import wrapper
from . import telemetry


@telemetry.instrument()
class PartFactoryStl(PartFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTL", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".stl")
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STL", part.project_name, part.name):
            wrapper_path = wrapper.get("stl.py")
            request = {}

            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            runtime = self.ctx.get_python_runtime("3.11")
            response_serialized, errors = await runtime.run_async(
                [wrapper_path, os.path.abspath(self.path)],
                request_serialized,
            )

            sys.stderr.write(errors)

            try:
                response = base64.b64decode(response_serialized)
                result = pickle.loads(response)
            except Exception as e:
                pc_logging.error(f"Failed to deserialize STL wrapper response: {e}")
                raise

            if not result.get("success", False):
                pc_logging.error(result.get("exception", "Unknown error"))
                raise Exception(result.get("exception", "Unknown error"))

            shape = result.get("shape")
            self.ctx.stats_parts_instantiated += 1

            return shape
