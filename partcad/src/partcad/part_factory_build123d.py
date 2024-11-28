#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
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

from .part_factory_python import PartFactoryPython
from . import wrapper
from . import logging as pc_logging

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from cq_serialize import register as register_cq_helper


class PartFactoryBuild123d(PartFactoryPython):
    def __init__(
        self, ctx, source_project, target_project, config, can_create=False
    ):
        python_version = source_project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = "3.10"
        if python_version == "3.12" or python_version == "3.11":
            pc_logging.debug(
                "Downgrading Python version to 3.10 to avoid compatibility issues with build123d"
            )
            python_version = "3.10"
        with pc_logging.Action(
            "InitBuild123d", target_project.name, config["name"]
        ):
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
                pc_logging.error(
                    "build123d script is empty or does not exist: %s"
                    % part.path
                )
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
                patch["\\Z"] = "\nshow_object(%s)\n" % self.config["showObject"]
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            register_cq_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            await self.runtime.ensure_async(
                "ocp-tessellate==3.0.8",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery==2.4.0",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "numpy==1.24.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "numpy-quaternion==2023.0.4",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "nptyping==2.0.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                # "typing_extensions>=4.6.0,<5", # doesn't work on Windows
                "typing_extensions==4.12.2",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "build123d==0.7.0",
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(part.path),
                    os.path.abspath(cwd),
                ],
                request_serialized,
            )
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
                # pc_logging.error("Response: %s" % response_serialized)
                response = base64.b64decode(response_serialized)
                register_cq_helper()
                result = pickle.loads(response)
            except Exception as e:
                part.error(
                    "Exception while deserializing %s: %s" % (part.name, e)
                )
                return None

            if not result["success"]:
                pc_logging.error("Failed to produce the part: %s" % part.name)
                return None

            self.ctx.stats_parts_instantiated += 1
            part.components = []

            if result["shapes"] is None:
                return None
            if len(result["shapes"]) == 0:
                return None

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
                        if isinstance(shape, TopLoc_Location) or isinstance(
                            shape, gp_Ax1
                        ):
                            continue

                        components_list.append(shape)

                        if (
                            not isinstance(shape, TopoDS_Edge)  # 1D
                            and not isinstance(shape, TopoDS_Wire)  # 1.5?D
                            and not isinstance(shape, TopoDS_Face)  # 2D
                        ):
                            builder.Add(compound, shape)
                    except Exception as e:
                        pc_logging.error(
                            "Error adding shape to compound: %s" % e
                        )

            process(result["shapes"], part.components)
            # pc_logging.info("Created: %s" % type(compound))

            return compound
