#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
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
class PartFactoryBuild123d(PartFactoryPython):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        python_version = source_project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
        with pc_logging.Action("InitBuild123d", target_project.name, config["name"]):
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

        with pc_logging.Action("Build123d", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("build123d script is empty or does not exist: %s" % part.path)
                return None

            # Finish initialization of PythonRuntime
            # which was too expensive to do in the constructor
            await self.prepare_python()

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("build123d.py")

            # Build the request
            request = {"build_parameters": {}}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    request["build_parameters"][param_name] = param["default"]
            # Which of the above the part's *type* contributed. The wrapper needs
            # it to tell a parameter the script forgot to declare (an error) from
            # one the script was never asked to want (not an error).
            request["object_type_parameters"] = self.object_type_parameter_names()
            patch = {}
            if "show" in self.config:
                patch["\\Z"] = "\nshow(%s)\n" % self.config["show"]
            if "showObject" in self.config:
                patch["\\Z"] = "\nshow_object(%s)\n" % self.config["showObject"]
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            with telemetry.start_as_current_span("*PartFactoryBuild123d.instantiate.{shape_envelope.serialize}"):
                request["name"] = "%s:%s" % (part.project_name, part.name)
                request["label"] = part.name
                request["kind"] = "part"
                request_serialized = shape_envelope.serialize(request)

            # TODO: @alexanderilyin: those should be read from the package/part config?
            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.TYPING_EXTENSIONS,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.OCPSVG,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.BUILD123D,
                session=self.session,
            )
            # Last: re-asserts the VTK-enabled OCP that build123d's
            # 'cadquery-ocp-novtk' dependency has just replaced.
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY_OCP,
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            command = [
                wrapper_path,
                os.path.abspath(part.path),
                os.path.abspath(cwd),
            ]
            pc_logging.debug("Command was: %s" % command)
            exitcode, response_serialized, errors = await self.runtime.run_async(
                command,
                request_serialized,
            )
            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (part.project_name, part.name)
                pc_logging.debug("%s: %s: Failed to execute command: '%s' with exitcode %s" % (part.project_name, part.name, " ".join(command), exitcode))

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    error_line = error_line.strip()
                    if not error_line:
                        continue
                    # TODO(clairbee): Move the part name concatenation to where the logging happens
                    # part.error("%s: %s" % (part.name, error_line))
                    part.error(error_line)

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                part.error("Exception while deserializing %s: %s" % (part.name, e))
                return None

            if not result["success"]:
                pc_logging.error("Failed to produce the part: %s" % part.name)
                return None

            self.ctx.stats_parts_instantiated += 1

            # The wrapper already compounded the result and split out the
            # components (see wrapper_common.combine), so nothing here touches
            # OCP - the factory just forwards the envelope.
            part.components = result.get("components", [])
            if not part.components:
                return None
            return result["shape"]
