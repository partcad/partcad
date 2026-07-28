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
class SketchFactoryDxf(SketchFactoryPython):
    tolerance = 0.000001
    include = []
    exclude = []

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitDXF", target_project.name, config["name"]):
            python_version = source_project.python_version
            if python_version is None:
                # Stay one step ahead of the minimum required Python version
                python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
            # CadQuery has no release for Python 3.10, so a package that asks
            # for it still gets rendered on the oldest interpreter it supports.
            python_version = sandbox_versions.at_least(
                python_version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY
            )
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=can_create,
                python_version=python_version,
                extension=".dxf",
            )

            if "tolerance" in config:
                self.tolerance = float(config["tolerance"])

            if "include" in config:
                if isinstance(config["include"], list):
                    self.include = config["include"]
                elif isinstance(config["include"], str):
                    self.include = [config["include"]]

            if "exclude" in config:
                if isinstance(config["exclude"], list):
                    self.exclude = config["exclude"]
                elif isinstance(config["exclude"], str):
                    self.exclude = [config["exclude"]]

            self._create(config)

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("DXF", sketch.project_name, sketch.name):
            try:
                wrapper_path = wrapper.get("import_dxf.py")

                request = {
                    "path": self.path,
                    "tolerance": self.tolerance,
                    "include": self.include,
                    "exclude": self.exclude,
                }
                request["name"] = "%s:%s" % (sketch.project_name, sketch.name)
                request["label"] = sketch.name
                request_serialized = shape_envelope.serialize(request)

                await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)
                await self.runtime.ensure_async(sandbox_versions.CADQUERY)
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
                pc_logging.exception("Failed to import the DXF file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
