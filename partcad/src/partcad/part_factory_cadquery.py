#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os

from .part_factory_python import PartFactoryPython
from . import wrapper
from . import shape_envelope
from . import logging as pc_logging

from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class PartFactoryCadquery(PartFactoryPython):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        python_version = source_project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
        # CadQuery has no release for Python 3.10, so a package that asks for
        # it still gets rendered on the oldest interpreter CadQuery supports.
        python_version = sandbox_versions.at_least(python_version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)
        with pc_logging.Action("InitCadQuery", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=can_create,
                python_version=python_version,
            )
            # Complement the config object here if necessary
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("CadQuery", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("CadQuery script is empty or does not exist: %s" % part.path)
                return None

            # Finish initialization of PythonRuntime
            # which was too expensive to do in the constructor
            await self.prepare_python()

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("cadquery.py")

            # Build the request
            request = {"build_parameters": {}}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    request["build_parameters"][param_name] = param["default"]
            patch = {}
            if "show" in self.config:
                patch["\\Z"] = "\nshow(%s)\n" % self.config["show"]
            if "showObject" in self.config:
                patch["\\Z"] = "\nshow_object(%s)\n" % self.config["showObject"]
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            with telemetry.start_as_current_span("*PartFactoryCadquery.instantiate.{shape_envelope.serialize}"):
                request["name"] = "%s:%s" % (part.project_name, part.name)
                request["label"] = part.name
                request["kind"] = "part"
                request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NLOPT,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NUMPY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.TYPING_EXTENSIONS,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY_OCP,
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            # TODO(clairbee): Move the following code to a separate method in wrapper.py
            command = [
                wrapper_path,
                os.path.abspath(part.path),
                os.path.abspath(cwd),
            ]
            exitcode, response_serialized, errors = await self.runtime.run_async(
                command,
                request_serialized,
                session=self.session,
            )

            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (part.project_name, part.name)
                pc_logging.debug("%s: %s: Failed to execute command: '%s' with exitcode %s" % (part.project_name, part.name, " ".join(command), exitcode))

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    part.error("%s: %s" % (part.name, error_line))

            try:
                result = shape_envelope.deserialize(response_serialized)
                pc_logging.debug("Response: %s" % result)
            except Exception as e:
                part.error("Exception while deserializing %s: %s" % (part.name, e))
                return None

            if not result["success"]:
                part.error("%s: %s" % (part.name, result["exception"]))
                return None

            self.ctx.stats_parts_instantiated += 1

            # The wrapper already compounded the result and split out the
            # components (see wrapper_common.combine), so the factory just
            # forwards the envelope - no OCP, no extra round-trip.
            part.components = result.get("components", [])
            if not part.components:
                return None
            return result["shape"]
