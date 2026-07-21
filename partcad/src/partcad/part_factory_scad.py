#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import base64
import os
import pickle
import shutil
import subprocess
import sys
import tempfile

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import telemetry
from . import wrapper

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


@telemetry.instrument()
class PartFactoryScad(PartFactoryFile):
    # The sandboxed runtime used to keep build123d out of the main process
    PYTHON_SANDBOX_VERSION = "3.11"

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
            # Complement the config object here if necessary
            self._create(config)

            for dep in self.config.get("dependencies", []):
                self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))

            self.project_dir = source_project.config_dir

            self.runtime = None  # Lazy initialization for subprocess runtime

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("OpenSCAD", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("OpenSCAD script is empty or does not exist: %s" % part.path)
                return None

            scad_path = shutil.which("openscad")
            if scad_path is None:
                raise Exception("OpenSCAD executable is not found. Please, install OpenSCAD first.")

            with telemetry.start_as_current_span(
                "PartFactoryScad.instantiate.*{asyncio.create_subprocess_exec}"
            ) as span:
                stl_path = tempfile.mktemp(".stl")
                args = [
                    scad_path,
                    "--export-format",
                    "binstl",
                    "-o",
                    stl_path,
                    part.path,
                ]
                span.set_attribute("cmd", " ".join(args))
                p = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                )
                _, errors = await p.communicate()

            errors = errors.decode()
            if p.returncode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (part.project_name, part.name)
                pc_logging.debug("%s: %s: Failed to execute command: '%s' with exitcode %s" % (part.project_name, part.name, " ".join(args), p.returncode))

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    pc_logging.debug("%s: %s" % (part.name, error_line))

            if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
                part.error("OpenSCAD failed to generate the STL file. Please, check the script.")
                return None

            # The mesh is imported by a wrapper script executed in a sandboxed
            # python runtime, so that build123d is not needed in this process.
            # The wrapper falls back onto 'import_stl' if 'Mesher' fails,
            # to work around the known problem in Mesher.
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

            wrapper_path = wrapper.get("import_mesh.py")

            request = {"fallback_import_stl": True}
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            await self.runtime.ensure_async("ocp-tessellate==3.0.9")
            await self.runtime.ensure_async("typing_extensions==4.12.2")
            await self.runtime.ensure_async("cadquery-ocp==7.7.2")
            await self.runtime.ensure_async("ocpsvg==0.3.4")
            await self.runtime.ensure_async("build123d==0.8.0")

            command = [
                wrapper_path,
                os.path.abspath(stl_path),
                os.path.abspath(self.project.config_dir),
            ]
            with telemetry.start_as_current_span("*PartFactoryScad.instantiate.{runtime.run_async}"):
                exitcode, response_serialized, errors = await self.runtime.run_async(
                    command,
                    request_serialized,
                )
            if exitcode != 0 and len(errors) == 0:
                errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

            if errors:
                part.error("%s: %s" % (part.name, errors))
                return None

            try:
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            except Exception as e:
                part.error("%s: %s" % (part.name, e))
                return None

            if not result["success"]:
                part.error("%s: %s" % (part.name, result["exception"]))
                return None

            shape = result["shape"]
            os.unlink(stl_path)

            self.ctx.stats_parts_instantiated += 1

            return shape
