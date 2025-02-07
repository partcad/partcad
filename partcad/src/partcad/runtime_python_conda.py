#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import importlib
import os
import shutil
import subprocess
import json
import platform

from . import runtime_python
from . import logging as pc_logging


class CondaPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "conda", version)

        self.initialized_conda = self.initialized
        self.conda_path = shutil.which("mamba")
        if self.conda_path is not None:
            self.is_mamba = True
            # TODO(clairbee): Initialize the environment variables properly, including PATH
            if platform.system() == "Windows":
                self.python_flags += ["--no-warn-script-location"]
        else:
            self.conda_path = shutil.which("conda")
        if self.conda_path is None:
            self.conda_cli = importlib.import_module("conda.cli.python_api")
            self.conda_cli.run_command("config", "--quiet")
            info_json, _, _ = self.conda_cli.run_command("info", "--json")
            info = json.loads(info_json)
            if "CONDA_EXE" in info["env_vars"]:
                self.conda_path = info["env_vars"]["CONDA_EXE"]
            else:
                root_prefix = info["root_prefix"]
                root_bin = os.path.join(root_prefix, "bin")
                root_scripts = os.path.join(root_prefix, "Scripts")
                search_paths = [
                    root_scripts,
                    root_bin,
                    root_prefix,
                ]
                if os.name == "nt":
                    search_path_strings = ";".join(search_paths)
                else:
                    search_path_strings = ":".join(search_paths)
                self.conda_path = shutil.which(
                    "conda",
                    path=search_path_strings,
                )

    def once(self):
        with self.lock:
            self.once_conda_locked()
        super().once()

    async def once_async(self):
        with self.lock:
            async with self.get_async_lock():
                self.once_conda_locked()
        await super().once_async()

    def once_conda_locked(self):
        if not self.initialized_conda:
            with pc_logging.Action("Conda", "create", self.version):
                if self.conda_path is None:
                    raise Exception("ERROR: PartCAD is configured to use conda, but conda is missing")

                try:
                    os.makedirs(self.path)

                    # Install new conda environment with the preferred Python version
                    p = subprocess.Popen(
                        [
                            self.conda_path,
                            "create",
                            "-y",
                            "-q",
                            "--json",
                            "-p",
                            self.path,
                            "python==%s" % self.version if self.is_mamba else "python=%s" % self.version,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        encoding="utf-8",
                    )
                    _, stderr = p.communicate()
                    if not stderr is None and stderr.strip() != "":
                        pc_logging.error("conda env install error: %s" % stderr)

                    # Install pip into the newly created conda environment
                    p = subprocess.Popen(
                        [
                            self.conda_path,
                            "install",
                            "-y",
                            "-q",
                            "--json",
                            "-p",
                            self.path,
                            "pip",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        encoding="utf-8",
                    )
                    _, stderr = p.communicate()
                    if not stderr is None and stderr.strip() != "":
                        pc_logging.error("conda pip install error: %s" % stderr)

                    self.initialized_conda = True
                except Exception as e:
                    shutil.rmtree(self.path)
                    raise e
