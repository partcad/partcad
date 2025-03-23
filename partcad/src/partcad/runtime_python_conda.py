#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import contextlib
import copy
from filelock import FileLock
import importlib
import os
import shutil
import subprocess
import json

from . import runtime_python
from . import logging as pc_logging
from . import telemetry

# Global lock for conda that can be shared across threads


@telemetry.instrument()
class CondaPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None, variant=None):
        if variant is None:
            sandbox_type_name = "conda"
            self.variant_packages = []
        else:
            sandbox_type_name = f"conda-{variant}"
            self.variant_packages = [f"{variant}"]
        super().__init__(ctx, sandbox_type_name, version)

        self.global_conda_lock = FileLock(os.path.join(ctx.user_config.internal_state_dir, ".conda.lock"))
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
            self.verify_conda()

    def verify_conda(self):
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
                elif stdout is None or stdout.strip() == "":
                    pc_logging.warning("conda venv check warning: empty version")
                    self.conda_initialized = False
                elif not stdout.strip().startswith(self.version):
                    pc_logging.warning("conda venv check warning: %s" % stdout)
                    self.conda_initialized = False
                else:
                    self.conda_initialized = True
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
            # See if it just got created
            if os.path.exists(self.path):
                self.verify_conda()

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
                attempts = 0
                while attempts < 3:
                    with telemetry.tracer.start_as_current_span(
                        "CondaPythonRuntime.once_conda_locked.*{subprocess.Popen.conda.create}"
                    ) as span:
                        args = [
                            self.conda_path,
                            "create",
                            "-y",
                            "-q",
                            "--json",
                            "-p",
                            self.path,
                            *self.variant_packages,
                            "python==%s" % self.version if self.is_mamba else "python=%s" % self.version,
                        ]
                        # Strip user home directory from the path, if any
                        sanitized_args = copy.copy(args)
                        sanitized_args[0] = os.path.join("...", os.path.basename(sanitized_args[0]))
                        sanitized_args[6] = os.path.join("...", os.path.basename(sanitized_args[6]))
                        span.set_attribute("cmd", " ".join(sanitized_args))

                        # Install new conda environment with the preferred Python version
                        p = subprocess.Popen(
                            args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=False,
                            encoding="utf-8",
                        )
                        _, stderr = p.communicate()

                    if not stderr is None and stderr.strip() != "":
                        # Handle most common sporadic conda/mamba failures
                        if "Found incorrect download" in stderr:
                            pc_logging.warn("conda env install error: %s" % stderr)
                            attempts += 1
                            continue
                        if "libmamba libarchive" in stderr:
                            pc_logging.warn("conda env install error: %s" % stderr)
                            attempts += 1
                            continue
                        if "Found incorrect download" in stderr:
                            pc_logging.warn("conda env install error: %s" % stderr)
                            attempts += 1
                            continue
                        pc_logging.error("conda env install error: %s" % stderr)
                    break

                with telemetry.tracer.start_as_current_span(
                    "CondaPythonRuntime.once_conda_locked.*{subprocess.Popen.install.pip}"
                ) as span:
                    args = [
                        self.conda_path,
                        "install",
                        "-y",
                        "-q",
                        "--json",
                        "-p",
                        self.path,
                        "pip",
                    ]
                    # Strip user home directory from the path, if any
                    sanitized_args = copy.copy(args)
                    sanitized_args[0] = os.path.join("...", os.path.basename(sanitized_args[0]))
                    sanitized_args[6] = os.path.join("...", os.path.basename(sanitized_args[6]))
                    span.set_attribute("cmd", " ".join(sanitized_args))

                    # Install pip into the newly created conda environment
                    p = subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        encoding="utf-8",
                    )
                    _, stderr = p.communicate()

                if not stderr is None and stderr.strip() != "":
                    pc_logging.warning("conda pip install error: %s" % stderr)
                if p.returncode != 0:
                    pc_logging.error("conda pip install return code: %s" % p.returncode)
                    self.conda_initialized = False
                else:
                    self.conda_initialized = True
            except Exception as e:
                shutil.rmtree(self.path)
                raise e
