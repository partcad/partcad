#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import os

from . import wrapper
from . import logging as pc_logging
from .sketch_factory_python import SketchFactoryPython

from . import shape_envelope

from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class SketchFactorySvg(SketchFactoryPython):
    flip_y = True
    ignore_visibility = False
    use_wires = False
    use_faces = False

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitSVG", target_project.name, config["name"]):
            python_version = source_project.python_version
            if python_version is None:
                # Stay one step ahead of the minimum required Python version
                python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=can_create,
                python_version=python_version,
                extension=".svg",
            )

            if "flip-y" in config:
                self.flip_y = bool(config["flip-y"])

            if "ignore-visibility" in config:
                self.ignore_visibility = bool(config["ignore-visibility"])

            if "use-wires" in config:
                self.use_wires = bool(config["use-wires"])

            if "use-faces" in config:
                self.use_faces = bool(config["use-faces"])

            self._create(config)

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("SVG", sketch.project_name, sketch.name):
            try:
                wrapper_path = wrapper.get("import_svg.py")

                request = {
                    "path": self.path,
                    "flip_y": self.flip_y,
                    "ignore_visibility": self.ignore_visibility,
                    "use_wires": self.use_wires,
                    "use_faces": self.use_faces,
                }
                request["name"] = "%s:%s" % (sketch.project_name, sketch.name)
                request["label"] = sketch.name
                request_serialized = shape_envelope.serialize(request)

                await self.runtime.ensure_async(sandbox_versions.OCPSVG)
                await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS)
                await self.runtime.ensure_async(sandbox_versions.BUILD123D)
                # Last: re-asserts the VTK-enabled OCP that build123d's
                # 'cadquery-ocp-novtk' dependency has just replaced.
                await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)
                command = [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(self.project.config_dir),
                ]
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
            except Exception as e:
                pc_logging.exception("Failed to import the SVG file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
