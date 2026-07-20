#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import asyncio
import contextlib
import copy
import hashlib
import os
import pathlib
import platform
import signal
import subprocess
import sys
import threading
from filelock import FileLock

from . import runtime
from . import logging as pc_logging
from . import telemetry


def get_local_partcad_pkg(dep: str) -> str:
    """Use local partcad package instead of the deployed one (specifically intended to be used during testing so that tests are applied on the latest changes corresponding to a PR)"""
    if os.environ.get("PC_PARTCAD_PACKAGE_SUB") is not None:
        return os.path.normpath(os.environ.get("PC_PARTCAD_PACKAGE_SUB"))
    return dep


# Dependencies are installed one "pip install" invocation at a time, so pip
# never sees the constraints of the whole environment at once and cannot detect
# a conflict between them. That matters most for cadquery-ocp: cadquery and
# ocpsvg cap it below 7.8, but build123d 0.8.0 asks only for ">=7.7.0", so a
# "pip install build123d==0.8.0" into an environment that does not already have
# cadquery-ocp pulls the newest release (7.9.x at the time of writing). Mixing
# OCP versions between cadquery and build123d loads two incompatible native
# libraries into one interpreter, which crashes the wrapper process with no
# Python traceback and no stderr at all.
#
# The install order happens to install cadquery-ocp before build123d today, so
# this is currently correct only by accident. These constraints are passed to
# every "pip install" so the bound holds regardless of order.
#
# build123d 0.8.0 also depends on "ocpsvg" with no bound whatsoever, and ocpsvg
# switched from cadquery-ocp to the cadquery-ocp-proxy package in 0.4. Since
# cadquery-ocp-proxy only exists for 7.9+, letting ocpsvg float pulls a 7.9
# native runtime back in alongside the 7.7.2 one, which is the same conflict by
# another route. Keep ocpsvg on the pre-proxy line to match cadquery-ocp.
PIP_CONSTRAINTS = [
    "cadquery-ocp>=7.7.0,<7.8",
    "ocpsvg>=0.3.4,<0.4",
]


def describe_exit_code(returncode: int) -> str:
    """Describe a process exit code, naming the signal if it was killed by one."""
    # POSIX reports a signal death as a negative returncode
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = "unknown signal"
        return "killed by signal %d (%s)" % (-returncode, name)
    # Windows surfaces native crashes as large unsigned status codes
    known_windows_faults = {
        3221225477: "EXCEPTION_ACCESS_VIOLATION",
        3221226356: "STATUS_HEAP_CORRUPTION",
    }
    if returncode in known_windows_faults:
        return "exit code %d (%s)" % (returncode, known_windows_faults[returncode])
    return "exit code %d" % returncode


class VenvLock:
    lock: FileLock

    def __init__(self, runtime: "PythonRuntime", venv: str):
        runtime.venv_locks_lock.acquire()

        # Setup lock for given venv.
        # If venv is None then use default (no venv)
        if venv is None:
            venv = f"{runtime.sandbox_dir}.default"
            venv_lock_name = f".{venv}.lock"
        else:
            venv_lock_name = f".{runtime.sandbox_dir}.{venv}.lock"
        if venv not in runtime.venv_locks:
            runtime.venv_locks[venv] = FileLock(
                os.path.join(runtime.ctx.user_config.internal_state_dir, venv_lock_name), thread_local=False
            )
        self.lock = runtime.venv_locks[venv]
        runtime.venv_locks_lock.release()

    def __enter__(self, *_args):
        self.lock.acquire()

    def __exit__(self, *_args):
        self.lock.release()


@telemetry.instrument()
class PythonRuntime(runtime.Runtime):
    def __init__(self, ctx, sandbox, version=None):
        self.venv_locks = {}
        self.venv_locks_lock = threading.Lock()

        if version is None:
            version = "%d.%d" % (sys.version_info.major, sys.version_info.minor)
        super().__init__(ctx, "py-" + sandbox + "-" + version)
        self.sandbox = sandbox
        self.version = version
        self.is_mamba = False

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

        self.pip_flags = []
        self.pip_install_flags = []
        if platform.system() == "Windows":
            self.pip_install_flags += ["--no-warn-script-location"]

        self.constraints_path = None

    def get_constraints_flags(self):
        """Return the pip flags that apply PIP_CONSTRAINTS to an install.

        The constraints file lives in the runtime sandbox and is shared by the
        runtime environment and every v-env created under it.
        """
        if self.constraints_path is None:
            constraints_path = os.path.join(self.path, "partcad-constraints.txt")
            try:
                os.makedirs(self.path, exist_ok=True)
                with open(constraints_path, "w") as f:
                    f.write("\n".join(PIP_CONSTRAINTS) + "\n")
                self.constraints_path = constraints_path
            except OSError as e:
                # Not being able to write constraints must not stop the install;
                # it only means we fall back to the previous ordering-dependent
                # behavior, so warn loudly instead of failing.
                pc_logging.warning("Failed to write pip constraints to %s: %s" % (constraints_path, e))
                return []
        return ["--constraint", self.constraints_path]

    def report_dependency_conflicts(self, exitcode, stdout, stderr, path=None):
        """Log whatever "pip check" reported. Never raises."""
        if exitcode == 0:
            return
        report = (stdout or stderr or "").strip()
        if not report:
            return
        # Deliberately not fatal: environments that are already inconsistent
        # keep working today, and failing them here would turn a diagnostic
        # into an outage. The point is that the conflict stops being silent.
        pc_logging.error("Dependency conflicts in %s:\n%s" % (path if path else self.path, report))

    def check_deps_onced_locked(self, path=None):
        """Report dependency conflicts in a freshly provisioned environment."""
        exitcode, stdout, stderr = self.run_onced_locked(["-m", "pip", "check"], path=path)
        self.report_dependency_conflicts(exitcode, stdout, stderr, path=path)

    async def check_deps_async_onced_locked(self, path=None):
        """Report dependency conflicts in a freshly provisioned environment."""
        exitcode, stdout, stderr = await self.run_async_onced_locked(["-m", "pip", "check"], path=path)
        self.report_dependency_conflicts(exitcode, stdout, stderr, path=path)

    def get_async_lock(self):
        if not hasattr(self.tls, "async_locks"):
            self.tls.async_locks = {}
        self_id = id(self)
        loop = asyncio.get_event_loop()
        loop_id = id(loop)
        if self_id not in self.tls.async_locks or self.tls.async_locks[self_id][1] != loop_id:
            self.tls.async_locks[self_id] = (asyncio.Lock(), loop_id)
        return self.tls.async_locks[self_id][0]

    @contextlib.contextmanager
    def sync_lock(self, session=None):
        """Lock the runtime and the venv environment for executing a command"""
        with self.lock:
            venv = session["hash"] if session is not None else None
            with VenvLock(self, venv):
                yield

    @contextlib.asynccontextmanager
    async def async_lock(self, session=None):
        """Lock the runtime and the venv environment for executing a command"""
        async with self.get_async_lock():
            with self.lock:
                venv = session["hash"] if session is not None else None
                with VenvLock(self, venv):
                    yield

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        """Lock the runtime and the venv environment for installation of packages"""
        yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        """Lock the runtime and the venv environment for installation of packages"""
        yield

    def once(self):
        with self.sync_lock():
            with self.sync_lock_install():
                if not self.initialized:
                    # Preinstall the most common packages to avoid race conditions
                    self.ensure_onced_locked("ocp-tessellate==3.0.9")
                    self.ensure_onced_locked("nlopt==2.9.1")
                    self.ensure_onced_locked("cadquery==2.5.2")
                    self.ensure_onced_locked("numpy==2.2.1")
                    self.ensure_onced_locked("typing_extensions==4.12.2")
                    self.ensure_onced_locked("cadquery-ocp==7.7.2")
                    self.ensure_onced_locked("ocpsvg==0.3.4")
                    self.ensure_onced_locked("build123d==0.8.0")
                    self.initialized = True

    async def once_async(self):
        async with self.async_lock():
            with self.sync_lock_install():
                if not self.initialized:
                    # Preinstall the most common packages to avoid
                    await self.ensure_async_onced_locked("ocp-tessellate==3.0.9")
                    await self.ensure_async_onced_locked("nlopt==2.9.1")
                    await self.ensure_async_onced_locked("cadquery==2.5.2")
                    await self.ensure_async_onced_locked("numpy==2.2.1")
                    await self.ensure_async_onced_locked("typing_extensions==4.12.2")
                    await self.ensure_async_onced_locked("cadquery-ocp==7.7.2")
                    await self.ensure_async_onced_locked("ocpsvg==0.3.4")
                    await self.ensure_async_onced_locked("build123d==0.8.0")
                    self.initialized = True

    def run(self, cmd, stdin="", cwd=None, session=None):
        self.once()
        return self.run_onced(cmd, stdin=stdin, cwd=cwd, session=session)

    def run_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        if session and session["dirty"]:
            # The venv environment has to be created
            venv_created = False
            with self.sync_lock():
                if not os.path.exists(session["path"]):
                    venv_created = True
                    with pc_logging.Action("v-env", self.version, session["name"]):
                        # Create the venv environment
                        pc_logging.debug("Creating venv: %s" % session["path"])
                        self.run_onced_locked(
                            [
                                "-m",
                                "venv",
                                "--upgrade-deps",
                                session["path"],
                            ]
                        )
            # Install of the dependencies into the venv environment
            for dep in session["deps"]:
                if dep == "partcad":
                    dep = get_local_partcad_pkg(dep)
                self.ensure_onced(dep, path=session["path"])
            if venv_created:
                self.check_deps_onced_locked(path=session["path"])

        with self.sync_lock(session):
            python_path = self.get_venv_python_path(session, path)
            cmd = [python_path, *self.python_flags, *cmd]
            pc_logging.debug("Running: %s", cmd)
            # pc_logging.debug("stdin: %s", stdin)
            with telemetry.start_as_current_span("PythonRuntime.run_onced.*{subprocess.Popen}") as span:
                # Strip user home directory from the path, if any
                sanitized_cmd = copy.copy(cmd)
                sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
                span.set_attribute("cmd", " ".join(sanitized_cmd))
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

            if stdout:
                pc_logging.debug("Output of %s: %s" % (cmd, stdout))
            if stderr:
                if p.returncode == 0:
                    pc_logging.warning("%s produced stderr: %s" % (cmd, stderr))
                    stderr = ""
                else:
                    pc_logging.error("Error in %s: %s" % (cmd, stderr))

            # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
            # f = open("/tmp/log", "w")
            # f.write("Completed: %s\n" % cmd)
            # f.write(" stdin: %s\n" % stdin)
            # f.write(" stderr: %s\n" % stderr)
            # f.write(" stdout: %s\n" % stdout)
            # f.close()

            # [Temporary Fix] Ignore exit code 3221226356(0xc0000374) and 3221225477(0xc0000005)
            # This is a known and open issue on Windows related to the cadquery import
            # For more information, see: https://github.com/CadQuery/cadquery/issues/1564
            exitcode = 0 if p.returncode in [3221226356, 3221225477] else p.returncode

            if exitcode != 0 and not stdout and not stderr:
                # Neither a traceback nor stderr means the interpreter died
                # before it could report anything, which is what a native crash
                # looks like: most often two incompatible OCP builds loaded into
                # one process. Say so here, otherwise the only symptom is an
                # unrelated AttributeError on a None shape much further away.
                pc_logging.error(
                    "%s terminated abnormally (%s) without any output. This usually means conflicting "
                    "native dependencies, such as mismatched cadquery-ocp versions, in %s"
                    % (cmd, describe_exit_code(p.returncode), path if path else self.path)
                )

            return exitcode, stdout, stderr

    def run_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        if session and session["dirty"]:
            # The venv environment has to be created
            venv_created = not os.path.exists(session["path"])
            if not os.path.exists(session["path"]):
                with pc_logging.Action("v-env", self.version, session["name"]):
                    # Create the venv environment
                    pc_logging.debug("Creating venv: %s" % session["path"])
                    self.run_onced_locked(
                        [
                            "-m",
                            "venv",
                            "--upgrade-deps",
                            session["path"],
                        ]
                    )
            # Install of the dependencies into the venv environment
            for dep in session["deps"]:
                if dep == "partcad":
                    dep = get_local_partcad_pkg(dep)
                self.ensure_onced_locked(dep, path=session["path"])
            if venv_created:
                self.check_deps_onced_locked(path=session["path"])

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.python_flags, *cmd]
        pc_logging.debug("Running: %s", cmd)
        # pc_logging.debug("stdin: %s", stdin)
        exitcode, stdout, stderr = super().run(cmd, stdin=stdin, cwd=cwd)
        return exitcode, stdout, stderr

    async def run_async(self, cmd, stdin="", cwd=None, session=None):
        await self.once_async()
        return await self.run_async_onced(cmd, stdin=stdin, cwd=cwd, session=session)

    async def run_async_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        if session and session["dirty"]:
            # The venv environment has to be created
            venv_created = False
            async with self.async_lock():
                if not os.path.exists(session["path"]):
                    venv_created = True
                    with pc_logging.Action("v-env", self.version, session["name"]):
                        # Create the venv environment
                        pc_logging.debug("Creating venv: %s" % session["path"])
                        await self.run_async_onced_locked(
                            [
                                "-m",
                                "venv",
                                "--upgrade-deps",
                                session["path"],
                            ]
                        )

            # Install of the dependencies into the venv environment
            for dep in session["deps"]:
                if dep == "partcad":
                    dep = get_local_partcad_pkg(dep)
                await self.ensure_async_onced(dep, path=session["path"])
            if venv_created:
                await self.check_deps_async_onced_locked(path=session["path"])

        async with self.async_lock(session):
            python_path = self.get_venv_python_path(session, path)
            cmd = [python_path, *self.python_flags, *cmd]
            pc_logging.debug("Running: %s", cmd)
            # pc_logging.debug("stdin: %s", stdin)
            with telemetry.start_as_current_span("PythonRuntime.run_async_onced.*{subprocess.Popen}") as span:
                # Strip user home directory from the path, if any
                sanitized_cmd = copy.copy(cmd)
                sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
                span.set_attribute("cmd", " ".join(sanitized_cmd))
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

            if stdout:
                pc_logging.debug("Output of %s: %s" % (cmd, stdout))
            if stderr:
                if p.returncode == 0:
                    pc_logging.warning("%s produced stderr: %s" % (cmd, stderr))
                    stderr = ""
                else:
                    pc_logging.error("Error in %s: %s" % (cmd, stderr))

            # TODO(clairbee): remove the below when a better troubleshooting mechanism is introduced
            # f = open("/tmp/log", "w")
            # f.write("Completed: %s\n" % cmd)
            # f.write(" stdin: %s\n" % stdin)
            # f.write(" stderr: %s\n" % stderr)
            # f.write(" stdout: %s\n" % stdout)
            # f.close()

            # [Temporary Fix] Ignore exit code 3221226356(0xc0000374) and 3221225477(0xc0000005)
            # This is a known and open issue on Windows related to the cadquery import
            # For more information, see: https://github.com/CadQuery/cadquery/issues/1564
            exitcode = 0 if p.returncode in [3221226356, 3221225477] else p.returncode

            if exitcode != 0 and not stdout and not stderr:
                # Neither a traceback nor stderr means the interpreter died
                # before it could report anything, which is what a native crash
                # looks like: most often two incompatible OCP builds loaded into
                # one process. Say so here, otherwise the only symptom is an
                # unrelated AttributeError on a None shape much further away.
                pc_logging.error(
                    "%s terminated abnormally (%s) without any output. This usually means conflicting "
                    "native dependencies, such as mismatched cadquery-ocp versions, in %s"
                    % (cmd, describe_exit_code(p.returncode), path if path else self.path)
                )

            return exitcode, stdout, stderr

    async def run_async_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        if session and session["dirty"]:
            # The venv environment has to be created
            venv_created = not os.path.exists(session["path"])
            if not os.path.exists(session["path"]):
                with pc_logging.Action("v-env", self.version, session["name"]):
                    # Create the venv environment
                    pc_logging.debug("Creating venv: %s" % session["path"])
                    await self.run_async_onced_locked(
                        [
                            "-m",
                            "venv",
                            "--upgrade-deps",
                            session["path"],
                        ]
                    )
            # Install of the dependencies into the venv environment
            for dep in session["deps"]:
                if dep == "partcad":
                    dep = get_local_partcad_pkg(dep)
                await self.ensure_async_onced_locked(dep, path=session["path"])
            if venv_created:
                await self.check_deps_async_onced_locked(path=session["path"])

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.python_flags, *cmd]
        pc_logging.debug("Running: %s", cmd)
        exitcode, stdout, stderr = await super().run_async(cmd, stdin=stdin, cwd=cwd)
        return exitcode, stdout, stderr

    def ensure(self, python_package, session=None, path=None):
        self.once()
        self.ensure_onced(python_package, session=session, path=path)

    def ensure_onced(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
        guard_path = os.path.join(path, ".partcad.installed." + python_package_hash)
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            with self.sync_lock():
                with self.sync_lock_install():
                    if not os.path.exists(guard_path):
                        item = python_package
                        if item == "partcad":
                            item = get_local_partcad_pkg(item)
                        if not path is None:
                            item += " in " + path
                        with pc_logging.Action("PipInst", self.version, item):
                            self.run_onced_locked(
                                [
                                    "-m",
                                    "pip",
                                    *self.pip_flags,
                                    "install",
                                    *self.pip_install_flags,
                                    *self.get_constraints_flags(),
                                    python_package,
                                ],
                                path=path,
                            )
                        pathlib.Path(guard_path).touch()

    def ensure_onced_locked(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
        guard_path = os.path.join(path, ".partcad.installed." + python_package_hash)
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            if not os.path.exists(guard_path):
                item = python_package
                if item == "partcad":
                    item = get_local_partcad_pkg(item)
                if not path is None:
                    item += " in " + path
                with pc_logging.Action("PipInst", self.version, item):
                    self.run_onced_locked(
                        [
                            "-m",
                            "pip",
                            *self.pip_flags,
                            "install",
                            *self.pip_install_flags,
                            *self.get_constraints_flags(),
                            python_package,
                        ],
                        path=path,
                    )
                pathlib.Path(guard_path).touch()

    async def ensure_async(self, python_package, session=None, path=None):
        await self.once_async()
        await self.ensure_async_onced(python_package, session=session, path=path)

    async def ensure_async_onced(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time
        python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
        guard_path = os.path.join(path, ".partcad.installed." + python_package_hash)
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            async with self.async_lock():
                with self.sync_lock_install():
                    if not os.path.exists(guard_path):
                        item = python_package
                        if item == "partcad":
                            item = get_local_partcad_pkg(item)
                        if not path is None:
                            item += " in " + path
                        with pc_logging.Action("PipInst", self.version, item):
                            await self.run_async_onced_locked(
                                [
                                    "-m",
                                    "pip",
                                    *self.pip_flags,
                                    "install",
                                    *self.pip_install_flags,
                                    *self.get_constraints_flags(),
                                    python_package,
                                ],
                                path=path,
                            )
                        pathlib.Path(guard_path).touch()

    async def ensure_async_onced_locked(self, python_package, session=None, path=None):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time

        python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
        guard_path = os.path.join(path, ".partcad.installed." + python_package_hash)
        if session:
            # Add the dependency to the session dependencies
            session["deps"].append(python_package)
            if not os.path.exists(guard_path):
                # Mark this session as needed if the dependency is not met by the runtime environment
                session["dirty"] = True
        else:
            if not os.path.exists(guard_path):
                item = python_package
                if item == "partcad":
                    item = get_local_partcad_pkg(item)
                if not path is None:
                    item += " in " + path
                with pc_logging.Action("PipInst", self.version, item):
                    await self.run_async_onced_locked(
                        [
                            "-m",
                            "pip",
                            *self.pip_flags,
                            "install",
                            *self.pip_install_flags,
                            *self.get_constraints_flags(),
                            python_package,
                        ],
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
            # TODO-218: @alexanderilyin: Add support for --hash=... in requirements.txt
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
            # Use local partcad package instead of the deployed one (specifically intended to be used during testing)
            if dep == "partcad":
                dep = get_local_partcad_pkg(dep)
            await self.ensure_async_onced(dep, session=session)

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
        name_hash = hashlib.sha256(name.encode()).hexdigest()[:16]
        venv_path = os.path.join(self.path, "v-env-" + name_hash)
        return {
            "name": name,
            "hash": name_hash,
            "path": venv_path,
            "dirty": False,
            "deps": [],
        }
