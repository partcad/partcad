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
import sys
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

        # find conda executable
        self.conda_path = CondaPythonRuntime.find_conda_executable()
        self.is_mamba = "mamba" in os.path.basename(self.conda_path).lower() if self.conda_path else False
        # TODO(clairbee): Initialize the environment variables properly, including PATH

        if self.conda_initialized:
            self.verify_conda()

    @staticmethod
    def find_conda_executable():
        conda_path = shutil.which("mamba")
        if conda_path:
            return conda_path

        conda_path = shutil.which("conda")
        if conda_path:
            return conda_path

        try:
            conda_cli = importlib.import_module("conda.cli.python_api")
            conda_cli.run_command(conda_cli.Commands.CONFIG, "--quiet")
            info_json, _, _ = conda_cli.run_command(conda_cli.Commands.INFO, "--json")
            info = json.loads(info_json)
            env_vars = info.get("env_vars", {})
            if "CONDA_EXE" in env_vars:
                return env_vars["CONDA_EXE"]

            root_prefix = info.get("root_prefix", "")
            if not root_prefix:
                return None

            search_paths = [os.path.join(root_prefix, "Scripts"), os.path.join(root_prefix, "bin"), root_prefix]
            search_path_str = os.pathsep.join(search_paths) if os.name == "nt" else ":".join(search_paths)

            return shutil.which("conda", path=search_path_str)
        except Exception as e:
            pc_logging.error(f"Error locating conda executable: {e}")
            return None

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
                if p.returncode != 0:
                    if stderr is not None and stderr.strip() != "":
                        pc_logging.warning("conda venv check error: %s" % stderr)
                    else:
                        pc_logging.warning(f"conda venv check error")
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

    def _subprocess_env(self):
        """Make the conda env's own libstdc++ win over the system one (Linux).

        conda-forge's ICU 78 (reached through build123d -> IPython -> sqlite3)
        links a libstdc++ that provides CXXABI_1.3.15. On older Linux hosts the
        system libstdc++ predates that symbol, and conda does not touch
        LD_LIBRARY_PATH, so the loader otherwise binds ICU to the system copy and
        the import dies. Prepend the env's lib dir (which carries a modern
        libstdc++ via the libstdcxx-ng install in once_conda_locked_attempt) so
        it is found first. No-op off Linux, where the parent env is inherited.
        """
        if not sys.platform.startswith("linux"):
            return None
        env = os.environ.copy()
        env_lib = os.path.join(self.path, "lib")
        previous = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = env_lib + (os.pathsep + previous if previous else "")
        return env

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
                    with telemetry.start_as_current_span(
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

                with telemetry.start_as_current_span(
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
                        # PNG rendering goes through reportlab's renderPM, whose
                        # only backend now is rlPyCairo -> pycairo -> cairo.
                        # pycairo has no Linux wheel, so pip has to compile it
                        # against a system cairo, which is not reliably present
                        # or discoverable inside this sandbox (it breaks on the
                        # ubuntu-22.04 runner, for instance). Bringing pycairo
                        # from conda-forge instead ships cairo with it and makes
                        # PNG output work without any system dependency; pip then
                        # sees it already satisfied and does not rebuild it.
                        "pycairo",
                    ]
                    if sys.platform.startswith("linux"):
                        # conda-forge's ICU 78 (pulled in through build123d ->
                        # IPython -> sqlite3 -> _sqlite3 -> libicui18n) links a
                        # libstdc++ that provides CXXABI_1.3.15, newer than the
                        # system libstdc++ on older Linux hosts (e.g. ubuntu-22.04).
                        # Ship a modern libstdc++ inside the env so that symbol is
                        # available; _subprocess_env() then puts the env's lib dir
                        # on the loader path so it wins. libstdcxx-ng is Linux-only.
                        args.append("libstdcxx-ng")
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
