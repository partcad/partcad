#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Parts defined by a Chili3D script (a '.chili' file).

The Chili3D twin of part_factory_cadquery / part_factory_build123d: the script
is not evaluated in this process but handed to a wrapper running in a sandboxed
Node.js, and what comes back is the same BREP envelope every other delegating
factory returns.
"""

import os

from .part_factory_javascript import PartFactoryJavaScript
from . import wrapper
from . import shape_envelope
from . import logging as pc_logging

from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class PartFactoryChili3d(PartFactoryJavaScript):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        javascript_version = source_project.javascript_version
        if javascript_version is None:
            javascript_version = sandbox_versions.DEFAULT_NODE_VERSION
        # Chili3D's wrapper resolves a script's bare imports through Node.js
        # module customization hooks, which arrived in 20.6; an older sandbox
        # would fail at bootstrap rather than at the interesting place.
        javascript_version = sandbox_versions.at_least(javascript_version, sandbox_versions.MIN_NODE_VERSION)
        with pc_logging.Action("InitChili3d", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=can_create,
                javascript_version=javascript_version,
                extension=".chili",
            )
            # Complement the config object here if necessary
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("Chili3d", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("Chili3D script is empty or does not exist: %s" % part.path)
                return None

            # Finish initialization of JavaScriptRuntime
            # which was too expensive to do in the constructor
            await self.prepare_javascript()

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("chili3d.mjs")

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
            with telemetry.start_as_current_span("*PartFactoryChili3d.instantiate.{shape_envelope.serialize}"):
                request["name"] = "%s:%s" % (part.project_name, part.name)
                request["label"] = part.name
                request["kind"] = "part"
                request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(
                sandbox_versions.CHILI3D,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.HAPPY_DOM,
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
                session=self.session,
            )

            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (part.project_name, part.name)
                pc_logging.debug(
                    "%s: %s: Failed to execute command: '%s' with exitcode %s"
                    % (part.project_name, part.name, " ".join(command), exitcode)
                )

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    error_line = error_line.strip()
                    if not error_line:
                        continue
                    part.error(error_line)

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                part.error("Exception while deserializing %s: %s" % (part.name, e))
                return None

            if not result["success"]:
                part.error("%s: %s" % (part.name, result["exception"]))
                return None

            self.ctx.stats_parts_instantiated += 1

            # The wrapper already compounded the result and split out the
            # components, so the factory just forwards the envelope.
            part.components = result.get("components", [])
            if not part.components:
                return None
            return result["shape"]
