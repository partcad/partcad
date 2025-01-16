#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os
import shutil
import subprocess
import tempfile
import base64
import pickle
import build123d as b3d

from .part_factory_file import PartFactoryFile
from .runtime_python import PythonRuntime

from . import wrapper
from ocp_serialize import register as register_ocp_helper
from . import logging as pc_logging


class PartFactoryScad(PartFactoryFile):
    runtime: PythonRuntime
    cwd: str

    def __init__(self, ctx, source_project, target_project, config, can_create=False):

        with pc_logging.Action("InitOpenSCAD", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".scad",
                can_create=can_create,
            )
            # FIXME: related to wrapper
            python_version = source_project.python_version
            if python_version is None:
                # Stay one step ahead of the minimum required Python version
                python_version = "3.10"
            if python_version == "3.12" or python_version == "3.11":
                pc_logging.debug("Downgrading Python version to 3.10 to avoid compatibility issues with CadQuery")
            python_version = "3.10"
            self.runtime = self.ctx.get_python_runtime(python_version)
            self.session = self.runtime.get_session(source_project.name)
            self.cwd = config.get("cwd", None)

            self._create(config)
            self.project_dir = source_project.config_dir

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("OpenSCAD", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("OpenSCAD script is empty or does not exist: %s" % part.path)
                return None
            # FIXME: NOT WORKING/ issue with OCP import on wrappers/wrapper_common.py
            # Finish initialization of PythonRuntime
            # which was too expensive to do in the constructor
            await self.prepare_python()
            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("openscad.py")

            # Build the request
            request = {"build_parameters": {}}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    request["build_parameters"][param_name] = param["default"]
            # Serialize the request
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()
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
                session=self.session,
            )
            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    part.error("%s: %s" % (part.name, error_line))

            try:
                # pc_logging.info("Response: %s" % response_serialized)
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            except Exception as e:
                part.error("Exception while deserializing %s: %s" % (part.name, e))
                return None

            if not result["success"]:
                part.error("%s: %s" % (part.name, result["exception"]))
                return None

            if result["newPath"] is None:
                return None
            # TODO: we might need to delete /tmp folder after the script is done
            self.path = result["newPath"]
            self.part.path = self.path
            scad_path = shutil.which("openscad")
            if scad_path is None:
                raise Exception("OpenSCAD executable is not found. Please, install OpenSCAD first.")

            stl_path = tempfile.mktemp(".stl")
            p = await asyncio.create_subprocess_exec(
                *[
                    scad_path,
                    "--export-format",
                    "binstl",
                    "-o",
                    stl_path,
                    part.path,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            _, errors = await p.communicate()
            if len(errors) > 0:
                error_lines = errors.decode().split("\n")
                for error_line in error_lines:
                    pc_logging.debug("%s: %s" % (part.name, error_line))

            if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
                part.error("OpenSCAD failed to generate the STL file. Please, check the script.")
                return None

            try:
                shape = b3d.Mesher().read(stl_path)[0].wrapped
            except:
                try:
                    # First, make sure it's not the known problem in Mesher
                    shape = b3d.import_stl(stl_path).wrapped
                except Exception as e:
                    part.error("%s: %s" % (part.name, e))
                    return None
            os.unlink(stl_path)

            self.ctx.stats_parts_instantiated += 1

            return shape
