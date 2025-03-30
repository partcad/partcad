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

import build123d as b3d

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class PartFactoryScad(PartFactoryFile):
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
            if len(errors) > 0:
                error_lines = errors.decode().split("\n")
                for error_line in error_lines:
                    pc_logging.debug("%s: %s" % (part.name, error_line))

            if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
                part.error("OpenSCAD failed to generate the STL file. Please, check the script.")
                return None
            with telemetry.start_as_current_span("*PartFactoryScad.instantiate.{build123d.import_stl}"):
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
