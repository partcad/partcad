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

from . import runtime_python
from . import logging as pc_logging


class CondaPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "conda", version)

        self.conda_path = shutil.which("conda")
        if self.conda_path is None:
            # This problem was on Windows
            # https://stackoverflow.com/questions/76342609/cannot-install-conda-with-pip-and-python-3-8
            # https://pypi.org/project/conda/
            # https://github.com/conda/conda/issues/11715
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
            if not self.initialized:
                with pc_logging.Action("Conda", "create", self.version):
                    if self.conda_path is None:
                        raise Exception(
                            "ERROR: PartCAD is configured to use conda, but conda is missing"
                        )

                    try:
                        os.makedirs(self.path)
                        # TODO: Add command logging for generated CLI command
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
                                "python=%s" % self.version,
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        _, stderr = p.communicate()
                        if not stderr is None and stderr != b"":
                            pc_logging.error(
                                "conda env install error: %s" % stderr
                            )

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
                        )
                        _, stderr = p.communicate()
                        if not stderr is None and stderr != b"":
                            pc_logging.error(
                                "conda pip install error: %s" % stderr
                            )

                        self.initialized = True
                    except Exception as e:
                        shutil.rmtree(self.path)
                        raise e

    async def run(self, cmd, stdin="", cwd=None):
        self.once()

        # TODO: Add debug logging for generated CLI command
        return await super().run(
            [
                self.conda_path,
                "run",
                "--no-capture-output",
                "-p",
                self.path,
                # TODO: Manually test on Windows
                os.path.join(
                    self.path, "bin", "python" if os.name != "nt" else "pythonw"
                ),
                # "python%s" % self.version,  # This doesn't work on Windows
            ]
            + cmd,
            stdin,
            cwd=cwd,
        )
