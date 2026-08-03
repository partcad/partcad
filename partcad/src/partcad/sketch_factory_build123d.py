#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import os

from .sketch_factory_python import SketchFactoryPython
from . import wrapper
from . import shape_envelope
from . import logging as pc_logging

from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class SketchFactoryBuild123d(SketchFactoryPython):
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

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("Build123d", sketch.project_name, sketch.name):
            if not os.path.exists(sketch.path) or os.path.getsize(sketch.path) == 0:
                pc_logging.error("build123d script is empty or does not exist: %s" % sketch.path)
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
            patch = {}
            if "show" in self.config:
                patch["\\Z"] = "\nshow(%s)\n" % self.config["show"]
            if "showObject" in self.config:
                patch["\\Z"] = "\nshow_object(%s)\n" % self.config["show"]
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            request["name"] = "%s:%s" % (sketch.project_name, sketch.name)
            request["label"] = sketch.name
            request["kind"] = "sketch"
            request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.OCPSVG,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.TYPING_EXTENSIONS,
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
                os.path.abspath(sketch.path),
                os.path.abspath(cwd),
            ]
            exitcode, response_serialized, errors = await self.runtime.run_async(
                command,
                request_serialized,
            )
            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (sketch.project_name, sketch.name)
                pc_logging.debug("%s: %s: Failed to execute command: '%s' with exitcode %s" % (sketch.project_name, sketch.name, " ".join(command), exitcode))

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    error_line = error_line.strip()
                    if not error_line:
                        continue
                    # TODO(clairbee): Move the sketch name concatenation to where the logging happens
                    # part.error("%s: %s" % (sketch.name, error_line))
                    sketch.error(error_line)

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                sketch.error("Exception while deserializing %s: %s" % (sketch.name, e))
                return None

            if not result["success"]:
                sketch.error("%s: %s" % (sketch.name, result["exception"]))
                return None

            self.ctx.stats_sketches_instantiated += 1

            # The wrapper compounded the sketch's edges/wires/faces and split out
            # the components (see wrapper_common.combine); the factory just
            # forwards the envelope, with no OCP.
            sketch.components = result.get("components", [])
            if not sketch.components:
                return None
            return result["shape"]
