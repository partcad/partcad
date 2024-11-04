#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import asyncio
import hashlib
import os
import pathlib
import subprocess
import sys
import threading

from . import runtime
from . import logging as pc_logging


class PythonRuntime(runtime.Runtime):
    def __init__(self, ctx, sandbox, version=None):
        if version is None:
            version = "%d.%d" % (sys.version_info.major, sys.version_info.minor)
        super().__init__(ctx, "python-" + sandbox + "-" + version)
        self.version = version

        # Runtimes are meant to be executed from dedicated threads, outside of
        # the asyncio event loop. So a threading lock is appropriate here.
        self.lock = threading.RLock()
        self.tls = threading.local()

        # Preinstall the most common packages to avoid race conditions
        # TODO(clairbee): Lock the entire runtime instead
        self.ensure("ocp-tessellate")
        self.ensure("cadquery")
        self.ensure("numpy==1.24.1")
        self.ensure("numpy-quaternion==2023.0.4")
        self.ensure("nptyping==1.4.4")
        self.ensure("typing_extensions>=4.6.0,<5")
        self.ensure("build123d>=0.7.0")

    def get_async_lock(self):
        if not hasattr(self.tls, "async_locks"):
            self.tls.async_locks = {}
        self_id = id(self)
        if self_id not in self.tls.async_locks:
            self.tls.async_locks[self_id] = asyncio.Lock()
        return self.tls.async_locks[self_id]

    def once(self):
        pass

    async def once_async(self):
        pass

    def run(self, cmd, stdin="", cwd=None):
        self.once()
        return self.run_onced(cmd, stdin=stdin, cwd=cwd)

    def run_onced(self, cmd, stdin="", cwd=None):
        pc_logging.debug("Running: %s", cmd)
        p = subprocess.Popen(
            # cmd,
            cmd[0],
            *cmd[1:],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=cwd,
        )
        stdout, stderr = p.communicate(
            input=stdin.encode(),
            # TODO(clairbee): add timeout
        )

        stdout = stdout.decode()
        stderr = stderr.decode()

        # if stdout:
        #     pc_logging.debug("Output of %s: %s" % (cmd, stdout))
        # if stderr:
        #     pc_logging.debug("Error of %s: %s" % (cmd, stderr))

        # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
        # f = open("/tmp/log", "w")
        # f.write("Completed: %s\n" % cmd)
        # f.write(" stdin: %s\n" % stdin)
        # f.write(" stderr: %s\n" % stderr)
        # f.write(" stdout: %s\n" % stdout)
        # f.close()

        return stdout, stderr

    async def run_async(self, cmd, stdin="", cwd=None):
        await self.once_async()
        return await self.run_async_onced(cmd, stdin=stdin, cwd=cwd)

    async def run_async_onced(self, cmd, stdin="", cwd=None):
        pc_logging.debug("Running: %s", cmd)
        p = await asyncio.create_subprocess_exec(
            # cmd,
            cmd[0],
            *cmd[1:],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=cwd,
        )
        stdout, stderr = await p.communicate(
            input=stdin.encode(),
            # TODO(clairbee): add timeout
        )

        stdout = stdout.decode()
        stderr = stderr.decode()

        # if stdout:
        #     pc_logging.debug("Output of %s: %s" % (cmd, stdout))
        # if stderr:
        #     pc_logging.debug("Error of %s: %s" % (cmd, stderr))

        # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
        # f = open("/tmp/log", "w")
        # f.write("Completed: %s\n" % cmd)
        # f.write(" stdin: %s\n" % stdin)
        # f.write(" stderr: %s\n" % stderr)
        # f.write(" stdout: %s\n" % stdout)
        # f.close()

        return stdout, stderr

    def ensure(self, python_package):
        self.once()

        python_package_hash = hashlib.sha256(
            python_package.encode()
        ).hexdigest()
        guard_path = os.path.join(
            self.path, ".partcad.installed." + python_package_hash
        )
        if not os.path.exists(guard_path):
            with pc_logging.Action("PipInst", self.version, python_package):
                self.run_onced(["-m", "pip", "install", python_package])
            pathlib.Path(guard_path).touch()

    async def ensure_async(self, python_package):
        await self.once_async()

        # TODO(clairbee): expire the guard file after a certain time

        python_package_hash = hashlib.sha256(
            python_package.encode()
        ).hexdigest()
        guard_path = os.path.join(
            self.path, ".partcad.installed." + python_package_hash
        )
        with self.lock:
            async with self.get_async_lock():
                if not os.path.exists(guard_path):
                    with pc_logging.Action(
                        "PipInst", self.version, python_package
                    ):
                        await self.run_async_onced(
                            ["-m", "pip", "install", python_package]
                        )
                    pathlib.Path(guard_path).touch()

    async def prepare_for_package(self, project):
        await self.once_async()

        # TODO(clairbee): expire the guard file after a certain time

        # Check if this project has python requirements
        requirements_path = os.path.join(project.path, "requirements.txt")
        if os.path.exists(requirements_path):
            # See if it was already prepared once
            project_hash = hashlib.sha256(project.path.encode()).hexdigest()
            flag_filename = ".partcad.project." + project_hash
            flag_path = os.path.join(self.path, flag_filename)
            with self.lock:
                async with self.get_async_lock():
                    if not os.path.exists(flag_path) or os.path.getmtime(
                        requirements_path
                    ) > os.path.getmtime(flag_path):
                        # Install requirements and remember when we did that
                        with pc_logging.Action(
                            "PipReqs", self.version, project.name
                        ):
                            await self.run_onced(
                                [
                                    "-m",
                                    "pip",
                                    "install",
                                    "-r",
                                    requirements_path,
                                ]
                            )
                        pathlib.Path(flag_path).touch()

        # Install dependencies of the package
        if "pythonRequirements" in project.config_obj:
            for req in project.config_obj["pythonRequirements"]:
                await self.ensure_async(req)

    async def prepare_for_shape(self, config):
        await self.once_async()

        # Install dependencies of this part
        if "pythonRequirements" in config:
            for req in config["pythonRequirements"]:
                await self.ensure_async(req)
