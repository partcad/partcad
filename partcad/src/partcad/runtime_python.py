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
from . import sync_threads


class VenvLock(object):
    def __init__(self, runtime, venv: str):
        runtime.venv_locks_lock.acquire()
        if not venv in runtime.venv_locks:
            runtime.venv_locks[venv] = threading.Lock()
        self.lock = runtime.venv_locks[venv]
        runtime.venv_locks_lock.release()

    def __enter__(self, *_args):
        self.lock.acquire()

    def __exit__(self, *_args):
        self.lock.release()


class AsyncVenvLock(object):
    def __init__(self, runtime, venv: str):
        self.runtime = runtime
        self.venv = venv

    async def __aenter__(self, *_args):
        await sync_threads.run_detached(self.runtime.venv_locks_lock.acquire)
        if not self.venv in self.runtime.venv_locks:
            self.runtime.venv_locks[self.venv] = threading.Lock()
        self.lock = self.runtime.venv_locks[self.venv]
        self.runtime.venv_locks_lock.release()

        await sync_threads.run_detached(self.lock.acquire)

    async def __aexit__(self, *_args):
        self.lock.release()


class PythonRuntime(runtime.Runtime):
    def __init__(self, ctx, sandbox, version=None):
        self.venv_locks = {}
        self.venv_locks_lock = threading.Lock()

        if version is None:
            version = "%d.%d" % (sys.version_info.major, sys.version_info.minor)
        super().__init__(ctx, "python-" + sandbox + "-" + version)
        self.version = version

        # Runtimes are meant to be executed from dedicated threads, outside of
        # the asyncio event loop. So a threading lock is appropriate here.
        self.lock = threading.RLock()
        self.tls = threading.local()

        # The path to the Python executable
        self.exec_path = None
        # The name of the Python executable to search for in bin folders
        self.exec_name = "python" if os.name != "nt" else "python.exe"

        # Isolate this sandbox environment from the rest of the system
        self.python_flags = ["-sOOIu"]

        # TODO(clairbee): To improve portability, warn about uses of default encoding
        # self.python_flags += ["-X", "warn_default_encoding=1"]

        # TODO(clairbee): add -P on 3.11+
        # if TODO version >= "3.11":
        #     self.python_flags.append("-P")

    def get_async_lock(self):
        if not hasattr(self.tls, "async_locks"):
            self.tls.async_locks = {}
        self_id = id(self)
        if self_id not in self.tls.async_locks:
            self.tls.async_locks[self_id] = asyncio.Lock()
        return self.tls.async_locks[self_id]

    def once(self):
        with self.lock:
            if not self.initialized:
                # Preinstall the most common packages to avoid race conditions
                # TODO(clairbee): Lock the entire runtime instead
                self.ensure_onced("ocp-tessellate==3.0.8")
                self.ensure_onced("cadquery==2.4.0")
                self.ensure_onced("numpy==1.24.1")
                self.ensure_onced("numpy-quaternion==2023.0.4")
                self.ensure_onced("nptyping==2.0.1")
                # self.ensure_onced("typing_extensions>=4.6.0,<5") # doesn't work on Windows
                self.ensure_onced("typing_extensions==4.12.2")
                self.ensure_onced("build123d==0.7.0")
                self.initialized = True

    async def once_async(self):
        with self.lock:
            async with self.get_async_lock():
                if not self.initialized:
                    # Preinstall the most common packages to avoid
                    # TODO(clairbee): Lock the entire runtime instead
                    await self.ensure_async_onced_locked(
                        "ocp-tessellate==3.0.8"
                    )
                    await self.ensure_async_onced_locked("cadquery==2.4.0")
                    await self.ensure_async_onced_locked("numpy==1.24.1")
                    await self.ensure_async_onced_locked(
                        "numpy-quaternion==2023.0.4"
                    )
                    await self.ensure_async_onced_locked("nptyping==2.0.1")
                    # await self.ensure_async_onced_locked("typing_extensions>=4.6.0,<5") # doesn't work on Windows
                    await self.ensure_async_onced_locked(
                        "typing_extensions==4.12.2"
                    )
                    await self.ensure_async_onced_locked("build123d==0.7.0")
                    self.initialized = True

    def run(self, cmd, stdin="", cwd=None, session=None):
        self.once()
        return self.run_onced(cmd, stdin=stdin, cwd=cwd, session=session)

    def run_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        if session and session["dirty"]:
            # The venv environment has to be created
            with VenvLock(self, session["hash"]):
                if not os.path.exists(session["path"]):
                    with pc_logging.Action(
                        "v-env", self.version, session["name"]
                    ):
                        # Create the venv environment
                        pc_logging.debug("Creating venv: %s" % session["path"])
                        self.run_onced(
                            [
                                "-m",
                                "venv",
                                "--upgrade-deps",
                                session["path"],
                            ]
                        )
                # Install of the dependencies into the venv environment
                for dep in session["deps"]:
                    self.ensure_onced_locked(dep, path=session["path"])

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.python_flags, *cmd]
        pc_logging.debug("Running: %s", cmd)
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            encoding="utf-8",
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
        if stderr:
            pc_logging.debug("Error in %s: %s" % (cmd, stderr))

        # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
        # f = open("/tmp/log", "w")
        # f.write("Completed: %s\n" % cmd)
        # f.write(" stdin: %s\n" % stdin)
        # f.write(" stderr: %s\n" % stderr)
        # f.write(" stdout: %s\n" % stdout)
        # f.close()

        return stdout, stderr

    async def run_async(self, cmd, stdin="", cwd=None, session=None):
        await self.once_async()
        return await self.run_async_onced(
            cmd, stdin=stdin, cwd=cwd, session=session
        )

    async def run_async_onced(
        self, cmd, stdin="", cwd=None, session=None, path=None
    ):
        if session and session["dirty"]:
            # The venv environment has to be created
            async with AsyncVenvLock(self, session["hash"]):
                if not os.path.exists(session["path"]):
                    with pc_logging.Action(
                        "v-env", self.version, session["name"]
                    ):
                        # Create the venv environment
                        pc_logging.debug("Creating venv: %s" % session["path"])
                        await self.run_async_onced(
                            [
                                "-m",
                                "venv",
                                "--upgrade-deps",
                                session["path"],
                            ]
                        )
                # Install of the dependencies into the venv environment
                for dep in session["deps"]:
                    await self.ensure_async_onced_locked(
                        dep, path=session["path"]
                    )

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.python_flags, *cmd]
        pc_logging.debug("Running: %s", cmd)
        p = await asyncio.create_subprocess_exec(
            *cmd,
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
        if stderr:
            pc_logging.error("Error in %s: %s" % (cmd, stderr))

        # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
        # f = open("/tmp/log", "w")
        # f.write("Completed: %s\n" % cmd)
        # f.write(" stdin: %s\n" % stdin)
        # f.write(" stderr: %s\n" % stderr)
        # f.write(" stdout: %s\n" % stdout)
        # f.close()

        return stdout, stderr

    def ensure(self, python_package, session=None, path=None):
        self.once()
        self.ensure_onced(python_package, session=session, path=path)

    def ensure_onced(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        python_package_hash = hashlib.sha256(
            python_package.encode()
        ).hexdigest()
        guard_path = os.path.join(
            path, ".partcad.installed." + python_package_hash
        )
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            if not os.path.exists(guard_path):
                item = python_package
                if not path is None:
                    item += " in " + path
                with pc_logging.Action("PipInst", self.version, item):
                    self.run_onced(
                        ["-m", "pip", "install", python_package], path=path
                    )
                pathlib.Path(guard_path).touch()

    async def ensure_async(self, python_package, session=None, path=None):
        await self.once_async()
        await self.ensure_async_onced(
            python_package, session=session, path=path
        )

    async def ensure_async_onced(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time

        python_package_hash = hashlib.sha256(
            python_package.encode()
        ).hexdigest()
        guard_path = os.path.join(
            path, ".partcad.installed." + python_package_hash
        )
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            with self.lock:
                async with self.get_async_lock():
                    if not os.path.exists(guard_path):
                        item = python_package
                        if not path is None:
                            item += " in " + path
                        with pc_logging.Action("PipInst", self.version, item):
                            await self.run_async_onced(
                                ["-m", "pip", "install", python_package],
                                path=path,
                            )
                        pathlib.Path(guard_path).touch()

    async def ensure_async_onced_locked(
        self, python_package, session=None, path=None
    ):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time

        python_package_hash = hashlib.sha256(
            python_package.encode()
        ).hexdigest()
        guard_path = os.path.join(
            path, ".partcad.installed." + python_package_hash
        )
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            if not os.path.exists(guard_path):
                item = python_package
                if not path is None:
                    item += " in " + path
                with pc_logging.Action("PipInst", self.version, item):
                    await self.run_async_onced(
                        ["-m", "pip", "install", python_package],
                        path=path,
                    )
                pathlib.Path(guard_path).touch()

    async def prepare_for_package(self, project, session=None):
        await self.once_async()

        # TODO(clairbee): expire the guard file after a certain time

        # Check if this project has python requirements
        dependencies = []

        # Install dependencies of the package
        if "pythonRequirements" in project.config_obj:
            reqs = project.config_obj["pythonRequirements"]
            if isinstance(reqs, str):
                reqs = reqs.strip().split("\n")
            for req in reqs:
                dependencies.append(req.strip())
        else:
            requirements_path = os.path.join(project.path, "requirements.txt")
            if os.path.exists(requirements_path):
                with open(requirements_path) as f:
                    requirements_text = f.read()
                requirements_lines = requirements_text.strip().split("\n")
                for line in requirements_lines:
                    line = line.strip()
                    if line.startswith("#"):
                        continue
                    dependencies.append(line)

        for dep in dependencies:
            await self.ensure_async(dep, session=session)

    async def prepare_for_shape(self, config, session=None):
        await self.once_async()

        # Install dependencies of this part
        if "pythonRequirements" in config:
            reqs = config["pythonRequirements"]
            if isinstance(reqs, str):
                reqs = reqs.strip().split("\n")
            for req in reqs:
                await self.ensure_async_onced(req.strip(), session)

    def get_venv_python_path(self, session=None, path=None):
        use_venv = False

        if path is None:
            if session is None or not session["dirty"]:
                # Use the full interpreter path if known
                if not self.exec_path is None:
                    return self.exec_path
                # If the full path is not known, use the interpreter name
                path = self.path
            else:
                path = session["path"]
                use_venv = True
        else:
            # This can be either a venv path or a conda path.
            if str(os.path.basename(path)).startswith("v-env-"):
                use_venv = True
            else:
                use_venv = False

        if os.name == "nt":
            if use_venv:
                python_path = os.path.join(path, "Scripts", self.exec_name)
            else:
                python_path = os.path.join(path, self.exec_name)
        else:
            python_path = os.path.join(path, "bin", self.exec_name)

        return python_path

    def get_session(self, name: str):
        """Create a context to describe the venv environment in case it is needed"""
        name_hash = hashlib.sha256(name.encode()).hexdigest()
        venv_path = os.path.join(self.path, "v-env-" + name_hash)
        return {
            "name": name,
            "hash": name_hash,
            "path": venv_path,
            "dirty": False,
            "deps": [],
        }
