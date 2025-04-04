#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle
import sys

from OCP.TopoDS import (
    TopoDS_Builder,
    TopoDS_Compound,
)

from .part_factory_python import PartFactoryPython
from . import wrapper
from . import logging as pc_logging

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper

from . import telemetry


@telemetry.instrument()
class PartFactoryCadquery(PartFactoryPython):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        python_version = source_project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = "3.11"
        if python_version == "3.12" or python_version == "3.10":
            # Switching Python version to 3.11 to avoid compatibility issues with CadQuery
            python_version = "3.11"
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
            register_ocp_helper()
            with telemetry.start_as_current_span("*PartFactoryCadquery.instantiate.{pickle.dumps}"):
                picklestring = pickle.dumps(request)
                request_serialized = base64.b64encode(picklestring).decode()

            await self.runtime.ensure_async(
                "ocp-tessellate==3.0.9",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "nlopt==2.9.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery==2.5.2",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "numpy==2.2.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "typing_extensions==4.12.2",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery-ocp==7.7.2",
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            # TODO(clairbee): Move the following code to a separate method in wrapper.py
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(part.path),
                    os.path.abspath(cwd),
                ],
                request_serialized,
                session=self.session,
            )
            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    part.error("%s: %s" % (part.name, error_line))

            try:
                # pc_logging.error("Response: %s" % response_serialized)
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            except Exception as e:
                part.error("Exception while deserializing %s: %s" % (part.name, e))
                return None

            if not result["success"]:
                part.error("%s: %s" % (part.name, result["exception"]))
                return None

            self.ctx.stats_parts_instantiated += 1

            if result["shapes"] is None:
                return None
            if len(result["shapes"]) == 0:
                return None
            if len(result["shapes"]) == 1:
                return result["shapes"][0]

            with telemetry.start_as_current_span("*PartFactoryCadquery.instantiate.{OCP.TopoDS.TopoDS_Builder}"):
                builder = TopoDS_Builder()
                compound = TopoDS_Compound()
                builder.MakeCompound(compound)
                for shape in result["shapes"]:
                    builder.Add(compound, shape)
            return compound
