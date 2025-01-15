#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle
import sys

from . import wrapper
from . import logging as pc_logging
from .sketch_factory_python import SketchFactoryPython

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


class SketchFactoryDxf(SketchFactoryPython):
    tolerance = 0.000001
    include = []
    exclude = []

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitDXF", target_project.name, config["name"]):
            python_version = source_project.python_version
            if python_version is None:
                # Stay one step ahead of the minimum required Python version
                python_version = "3.11"
            if python_version == "3.12" or python_version == "3.10":
                pc_logging.debug("Switching Python version to 3.11 to avoid compatibility issues with CadQuery")
                python_version = "3.11"
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
                register_ocp_helper()
                picklestring = pickle.dumps(request)
                request_serialized = base64.b64encode(picklestring).decode()

                await self.runtime.ensure_async("cadquery-ocp==7.7.2")
                await self.runtime.ensure_async("cadquery==2.5.2")
                response_serialized, errors = await self.runtime.run_async(
                    [
                        wrapper_path,
                        os.path.abspath(self.path),
                        os.path.abspath(self.project.config_dir),
                    ],
                    request_serialized,
                )
                sys.stderr.write(errors)

                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)

                if not result["success"]:
                    pc_logging.error(result["exception"])
                    raise Exception(result["exception"])

                shape = result["shape"]
            except Exception as e:
                pc_logging.exception("Failed to import the DXF file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
