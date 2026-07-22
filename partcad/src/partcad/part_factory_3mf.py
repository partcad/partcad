#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle
import sys

from . import telemetry
from . import wrapper
from .part_factory_file import PartFactoryFile
from . import logging as pc_logging

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


@telemetry.instrument()
class PartFactory3mf(PartFactoryFile):
    # The sandboxed runtime used to keep build123d out of the main process
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("Init3MF", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".3mf",
            )
            # Complement the config object here if necessary
            self._create(config)

            self.runtime = None  # Lazy initialization for subprocess runtime

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("3MF", part.project_name, part.name):
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

            wrapper_path = wrapper.get("import_mesh.py")

            request = {"fallback_import_stl": False}
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            await self.runtime.ensure_async("ocp-tessellate==3.0.9")
            await self.runtime.ensure_async("typing_extensions==4.12.2")
            await self.runtime.ensure_async("cadquery-ocp==7.7.2")
            await self.runtime.ensure_async("ocpsvg==0.3.4")
            await self.runtime.ensure_async("build123d==0.8.0")

            command = [
                wrapper_path,
                os.path.abspath(self.path),
                os.path.abspath(self.project.config_dir),
            ]
            with telemetry.start_as_current_span("*PartFactory3mf.instantiate.{runtime.run_async}"):
                exitcode, response_serialized, errors = await self.runtime.run_async(
                    command,
                    request_serialized,
                )
            if exitcode != 0 and len(errors) == 0:
                errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            response = base64.b64decode(response_serialized)
            register_ocp_helper()
            result = pickle.loads(response)

            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])

            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1

            return shape
