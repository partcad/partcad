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
import build123d as b3d
import hashlib
import tempfile
import fcntl  # For file locking

from .part_factory_file import PartFactoryFile

from . import logging as pc_logging


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
            self.pre_process_scad()
            self._create(config)
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

    def pre_process_scad(self):
        """
        Preprocess a SCAD file by:
        - appending module call to the end of SCAD file.
        - updates self.path to the new file path
        """
        args: dict = {}
        method: str = None
        args_str: str = ""

        if "parameters" in self.config:
            for param_name, param in self.config["parameters"].items():
                if param_name == "method":
                    method = param["default"]
                else:
                    args[param_name] = param["default"]
        if method is None:
            return

        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())

        new_line = f"{method}({args_str});"

        base_dir = os.path.dirname(self.path)
        if not base_dir:
            base_dir = "."

        lock_path = "/tmp/partcad.lock"
        with open(lock_path, "w") as lock_file:
            fcntl.lockf(lock_file, fcntl.LOCK_EX)

            try:
                if ".partcad/git" in base_dir.replace("\\", "/"):
                    # Create a stable name for the SCAD file
                    hashed = hashlib.sha1(base_dir.encode("utf-8")).hexdigest()
                    original_filename = os.path.basename(self.path)
                    new_filename = f"partcad_{hashed}_{original_filename}"
                    new_scad_path = os.path.join(base_dir, new_filename)

                    print(f"Detected '.partcad/git' in path. Copying to {new_scad_path} ...")
                    shutil.copy(self.path, new_scad_path)

                    # Read the content
                    with open(new_scad_path, "r") as f:
                        lines = f.readlines()
                    non_commented_lines = []
                    for line in lines:
                        stripped = line.strip()
                        # If the line starts with `//`, skip it, its commented
                        if stripped.startswith("//"):
                            continue
                        non_commented_lines.append(line)

                    non_commented_content_str = "".join(non_commented_lines)

                    # Check if the method call already exists
                    if new_line not in non_commented_content_str:
                        content = "".join(lines)
                        updated_content = f"{content}\n{new_line}"
                        with open(new_scad_path, "w") as f:
                            f.write(updated_content)

                    self.path = new_scad_path

                else:
                    hashed = hashlib.sha1(base_dir.encode("utf-8")).hexdigest()
                    tmp_package_dir = f"/tmp/partcad-openscad-{hashed}"

                    # Copy entire base_dir to tmp_package_dir if not already present
                    if not os.path.exists(tmp_package_dir):
                        shutil.copytree(base_dir, tmp_package_dir)

                    # Name of the SCAD file in the tmp directory
                    scad_filename = os.path.basename(self.path)
                    new_scad_path = os.path.join(tmp_package_dir, scad_filename)

                    # Overwrite the file from original source
                    shutil.copy(self.path, new_scad_path)

                    # Read its content
                    with open(new_scad_path, "r") as f:
                        lines = f.readlines()
                        # 1) Build a string of *non-commented* lines only
                    non_commented_lines = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("//"):
                            continue
                        non_commented_lines.append(line)

                    non_commented_content_str = "".join(non_commented_lines)
                    if new_line not in non_commented_content_str:
                        content = "".join(lines)
                        updated_content = f"{content}\n{new_line}"
                        with open(new_scad_path, "w") as f:
                            f.write(updated_content)

                    # Update self.path to the new file location
                    self.path = new_scad_path

            finally:
                # Release the lock
                fcntl.lockf(lock_file, fcntl.LOCK_UN)
