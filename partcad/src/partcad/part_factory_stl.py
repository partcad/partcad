#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import os

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import wrapper
from . import telemetry

from . import shape_envelope


@telemetry.instrument()
class PartFactoryStl(PartFactoryFile):
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTL", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".stl")
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STL", part.project_name, part.name):
            wrapper_path = wrapper.get("stl.py")
            request = {}

            request["name"] = "%s:%s" % (part.project_name, part.name)
            request["label"] = part.name
            request_serialized = shape_envelope.serialize(request)

            runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)
            with telemetry.start_as_current_span("*PartFactoryStl.instantiate.{runtime.run_async}"):
                command = [wrapper_path, os.path.abspath(self.path)]
                exitcode, response_serialized, errors = await runtime.run_async(
                    command,
                    request_serialized,
                )
                if exitcode != 0 and len(errors) == 0:
                    errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                pc_logging.error(f"Failed to deserialize STL wrapper response: {e}")
                raise

            if not result.get("success", False):
                pc_logging.error(result.get("exception", "Unknown error"))
                raise Exception(result.get("exception", "Unknown error"))

            shape = result.get("shape")
            self.ctx.stats_parts_instantiated += 1

            return shape
