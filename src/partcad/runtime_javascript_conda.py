#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A JavaScript sandbox whose Node.js is provisioned by conda.

The twin of runtime_python_conda: conda creates an environment holding the
requested Node.js major version, so a package that asks for one PartCAD's host
does not have gets it anyway. The dependency trees are then installed into that
environment by the npm that ships with it, using the layout the base class
defines.
"""

import contextlib
import copy
import os
import shutil
import subprocess
import sys

from partcad_utils import conda as pc_conda

from . import runtime_javascript
from . import runtime_python_conda
from . import sandbox_lock
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class CondaJavaScriptRuntime(runtime_javascript.JavaScriptRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "conda", version)

        # Shared with the Python conda runtimes on purpose, and now actually
        # the same object as theirs: conda serializes poorly against itself
        # whatever it is installing, and the lock is over conda rather than over
        # a particular environment (see sandbox_lock.conda).
        self.global_conda_lock = sandbox_lock.conda(ctx.user_config.internal_state_dir)
        self.conda_initialized = self.initialized

        self.conda_path = runtime_python_conda.CondaPythonRuntime.find_conda_executable()
        self.is_mamba = "mamba" in os.path.basename(self.conda_path).lower() if self.conda_path else False

        if self.conda_initialized:
            self.verify_conda()

    def get_node_path(self):
        if os.name == "nt":
            return os.path.join(self.path, self.exec_name)
        return os.path.join(self.path, "bin", self.exec_name)

    def get_npm_path(self):
        if os.name == "nt":
            # conda lays the Windows Node.js out the way the official installer
            # does: the launchers sit next to the environment root.
            return os.path.join(self.path, self.npm_name)
        return os.path.join(self.path, "bin", self.npm_name)

    def verify_conda(self):
        """Best-effort check that the environment holds a usable Node.js."""
        node_path = self.get_node_path()
        if not os.path.exists(node_path):
            self.conda_initialized = False
            return
        try:
            p = subprocess.Popen(
                [node_path, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                encoding="utf-8",
            )
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                pc_logging.warning("conda node check error: %s" % (stderr.strip() if stderr else p.returncode))
                self.conda_initialized = False
            elif not stdout or not stdout.strip():
                pc_logging.warning("conda node check warning: empty version")
                self.conda_initialized = False
            elif not stdout.strip().lstrip("v").startswith(self.version + "."):
                pc_logging.warning("conda node check warning: %s" % stdout)
                self.conda_initialized = False
            else:
                self.conda_initialized = True
        except Exception as e:
            pc_logging.warning("conda node check error: %s" % e)
            self.conda_initialized = False

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        with self.global_conda_lock.acquire(write=True):
            yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        """The asynchronous twin of sync_lock_install().

        Waits for conda asynchronously, for the reason CondaPythonRuntime's
        does: the lock is held across 'await's, so a task waiting for it by
        blocking would be blocking the loop the holder runs on.
        """
        async with self.global_conda_lock.acquire_async(write=True):
            yield

    def _subprocess_env(self):
        """Make the conda environment's own libstdc++ win over the system one.

        Same reasoning as CondaPythonRuntime._subprocess_env(): conda does not
        touch LD_LIBRARY_PATH, so on an older Linux host the loader binds the
        environment's binaries to a system libstdc++ that predates the symbols
        they were built against. No-op off Linux, where only what the base class
        does - putting the environment's Node.js on PATH - applies.
        """
        env = super()._subprocess_env()
        if not sys.platform.startswith("linux"):
            return env
        env_lib = os.path.join(self.path, "lib")
        previous = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = env_lib + (os.pathsep + previous if previous else "")
        return env

    def conda_command_env(self):
        """The environment to run the conda executable itself in.

        The twin of CondaPythonRuntime.conda_command_env(), and for the same
        reason: the conda a standalone bundle carries has no root prefix of its
        own, so it is told to keep its package cache under PartCAD's internal
        state directory. A host conda is left entirely alone.
        """
        if not pc_conda.is_bundled(self.conda_path):
            return None
        return pc_conda.bundled_command_env(self.ctx.user_config.internal_state_dir)

    def once(self):
        with self.sync_lock():
            self.once_conda_locked()
        super().once()

    async def once_async(self):
        async with self.async_lock():
            await self.once_conda_locked_async()
        await super().once_async()

    def once_conda_locked(self):
        with self.sync_lock_install():
            self.once_conda_holding_install_lock()

    async def once_conda_locked_async(self):
        """once_conda_locked() for a caller that is running on an event loop.

        Only the wait is asynchronous; see CondaPythonRuntime's counterpart.
        """
        async with self.async_lock_install():
            self.once_conda_holding_install_lock()

    def once_conda_holding_install_lock(self):
        """Create the conda environment. The conda lock is already held."""
        # See if it just got created
        if os.path.exists(self.path):
            self.verify_conda()

        if not self.conda_initialized:
            self.once_conda_locked_attempt()
            if not self.conda_initialized:
                # Sometimes it fails to create from the first attempt
                self.once_conda_locked_attempt()
            if not self.conda_initialized:
                raise Exception("ERROR: Conda environment initialization failed")

    def once_conda_locked_attempt(self):
        with pc_logging.Action("Conda", "create", "node-" + self.version):
            if self.conda_path is None:
                raise Exception("ERROR: PartCAD is configured to use conda, but conda is missing")

            try:
                with telemetry.start_as_current_span(
                    "CondaJavaScriptRuntime.once_conda_locked.*{subprocess.Popen.conda.create}"
                ) as span:
                    args = [
                        self.conda_path,
                        "create",
                        "-y",
                        "-q",
                        "--json",
                        "-p",
                        self.path,
                        # Fuzzy ('=') rather than exact ('=='), unlike the Python
                        # twin: self.version is a major line only, and there is no
                        # conda package whose version is literally "22" - '=22'
                        # is what matches 22.x. mamba reads it the same way.
                        "nodejs=%s" % self.version,
                    ]
                    # Strip user home directory from the path, if any
                    sanitized_args = copy.copy(args)
                    sanitized_args[0] = os.path.join("...", os.path.basename(sanitized_args[0]))
                    sanitized_args[6] = os.path.join("...", os.path.basename(sanitized_args[6]))
                    span.set_attribute("cmd", " ".join(sanitized_args))

                    p = subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        encoding="utf-8",
                        env=self.conda_command_env(),
                    )
                    _, stderr = p.communicate()

                if stderr is not None and stderr.strip() != "":
                    pc_logging.warning("conda node install error: %s" % stderr)
                if p.returncode != 0:
                    pc_logging.error("conda node install return code: %s" % p.returncode)
                    self.conda_initialized = False
                else:
                    self.verify_conda()
            except Exception as e:
                shutil.rmtree(self.path, ignore_errors=True)
                raise e
