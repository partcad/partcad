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

from OCP.gp import gp_Ax1
from OCP.TopoDS import (
    TopoDS_Builder,
    TopoDS_Compound,
    TopoDS_Edge,
    TopoDS_Wire,
    TopoDS_Face,
)
from OCP.TopLoc import TopLoc_Location

from .sketch_factory_python import SketchFactoryPython
from . import wrapper
from . import logging as pc_logging

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper

from . import telemetry


@telemetry.instrument()
class SketchFactoryCadquery(SketchFactoryPython):
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

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("CadQuery", sketch.project_name, sketch.name):
            if not os.path.exists(sketch.path) or os.path.getsize(sketch.path) == 0:
                pc_logging.error("CadQuery script is empty or does not exist: %s" % sketch.path)
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
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            register_ocp_helper()
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
                "cadquery-ocp==7.7.2",
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
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(sketch.path),
                    os.path.abspath(cwd),
                ],
                request_serialized,
            )
            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    sketch.error("%s: %s" % (sketch.name, error_line))

            try:
                # pc_logging.error("Response: %s" % response_serialized)
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            except Exception as e:
                sketch.error("Exception while deserializing %s: %s" % (sketch.name, e))
                return None

            if not result["success"]:
                sketch.error("%s: %s" % (sketch.name, result["exception"]))
                return None

            self.ctx.stats_sketches_instantiated += 1

            if result["shapes"] is None:
                return None
            if len(result["shapes"]) == 0:
                return None
            if len(result["shapes"]) == 1:
                return result["shapes"][0]

            builder = TopoDS_Builder()
            compound = TopoDS_Compound()
            builder.MakeCompound(compound)

            def process(shapes, components_list):
                for shape in shapes:
                    # pc_logging.info("Returned: %s" % type(shape))
                    try:
                        if shape is None or isinstance(shape, str):
                            # pc_logging.info("String: %s" % shape)
                            continue

                        if isinstance(shape, list):
                            child_component_list = list()
                            process(shape, child_component_list)
                            components_list.append(child_component_list)
                            continue

                        # TODO(clairbee): add support for the below types
                        if isinstance(shape, TopLoc_Location) or isinstance(shape, gp_Ax1):
                            continue

                        if (
                            isinstance(shape, TopoDS_Edge)
                            or isinstance(shape, TopoDS_Wire)
                            or isinstance(shape, TopoDS_Face)
                        ):
                            builder.Add(compound, shape)
                            components_list.append(shape)
                        elif False:
                            # TODO(clairbee) Add all metadata types here
                            components_list.append(shape)
                        else:
                            pc_logging.error("Unsupported shape type: %s" % type(shape))
                    except Exception as e:
                        pc_logging.error("Error adding shape to compound: %s" % e)

            process(result["shapes"], sketch.components)

            return compound
