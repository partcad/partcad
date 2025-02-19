#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import contextlib
from filelock import FileLock
import importlib
import os
import shutil
import subprocess
import json

from . import runtime_python
from . import logging as pc_logging
from .user_config import user_config

# Global lock for conda that can be shared across threads


class CondaPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None, variant=None):
        if variant is None:
            sandbox_type_name = "conda"
            self.variant_packages = []
        else:
            sandbox_type_name = f"conda-{variant}"
            self.variant_packages = [f"{variant}"]
        super().__init__(ctx, sandbox_type_name, version)

        self.global_conda_lock = FileLock(os.path.join(user_config.internal_state_dir, ".conda.lock"))
        self.conda_initialized = self.initialized

        self.conda_path = shutil.which("mamba")
        if self.conda_path is not None:
            self.is_mamba = True
            # TODO(clairbee): Initialize the environment variables properly, including PATH
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

        if self.conda_initialized:
            # Make a best effort attempt to determine if it's valid
            python_path = self.get_venv_python_path()
            if os.path.exists(python_path):
                try:
                    p = subprocess.Popen(
                        [python_path, "-c", "import sys; print(sys.version)"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        encoding="utf-8",
                    )
                    stdout, stderr = p.communicate()
                    if not stderr is None and stderr.strip() != "":
                        pc_logging.warning("conda venv check error: %s" % stderr)
                        self.conda_initialized = False
                    elif not stdout is None and stdout.strip() != "":
                        if not stdout.strip().startswith("Python %s" % self.version):
                            pc_logging.warning("conda venv check warning: %s" % stdout)
                            self.conda_initialized = False
                except Exception as e:
                    pc_logging.warning("conda venv check error: %s" % e)
                    self.conda_initialized = False

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        with self.global_conda_lock:
            yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        with self.global_conda_lock:
            yield

    def once(self):
        with self.sync_lock():
            self.once_conda_locked()
        super().once()

    async def once_async(self):
        async with self.async_lock():
            self.once_conda_locked()
        await super().once_async()

    def once_conda_locked(self):
        with self.sync_lock_install():
            if not self.conda_initialized:
                self.once_conda_locked_attempt()
            if not self.conda_initialized:
                # Sometime it fails to create from the first attempt
                self.once_conda_locked_attempt()
            # TODO(clairbee): Does it make sense to retry more than once?
            if not self.conda_initialized:
                raise Exception("ERROR: Conda environment initialization failed")

    # TODO(clairbee): Make an async version of this function
    def once_conda_locked_attempt(self):
        with pc_logging.Action("Conda", "create", self.version):
            if self.conda_path is None:
                raise Exception("ERROR: PartCAD is configured to use conda, but conda is missing")

            try:
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
                        *self.variant_packages,
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
                    self.conda_initialized = False
                else:
                    self.conda_initialized = True
            except Exception as e:
                shutil.rmtree(self.path)
                raise e
