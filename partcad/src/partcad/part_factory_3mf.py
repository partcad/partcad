#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import os

from . import sandbox_versions
from . import telemetry
from . import wrapper
from .part_factory_file import PartFactoryFile
from . import logging as pc_logging

from . import shape_envelope


@telemetry.instrument()
class PartFactory3mf(PartFactoryFile):
    # The sandboxed runtime used to keep build123d out of the main process
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

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
            request["name"] = "%s:%s" % (part.project_name, part.name)
            request["label"] = part.name
            request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE)
            await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS)
            await self.runtime.ensure_async(sandbox_versions.OCPSVG)
            await self.runtime.ensure_async(sandbox_versions.BUILD123D)
            # Last: re-asserts the VTK-enabled OCP that build123d's
            # 'cadquery-ocp-novtk' dependency has just replaced.
            await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

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

            result = shape_envelope.deserialize(response_serialized)

            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])

            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1

            return shape
