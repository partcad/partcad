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

from . import sandbox_versions
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
# a conflict between them. That matters most for OCP: loading two OCP builds
# into one interpreter crashes the wrapper process with no Python traceback and
# no stderr at all. These constraints are passed to every "pip install" so the
# bound holds regardless of the order the factories install things in.
#
# Since 7.9 both 'cadquery-ocp' (what cadquery depends on) and
# 'cadquery-ocp-novtk' (what build123d 0.11 depends on) declare
# 'cadquery-ocp-proxy' at the exact same version, so bounding the proxy is what
# keeps a single OCP generation in the sandbox -- capping only 'cadquery-ocp'
# would leave the novtk edge free to pull a different one.
#
# Note this does NOT decide which of the two builds wins: they ship the same
# native module and overwrite each other. That is handled by install ordering,
# see sandbox_versions.GUARD_INVALIDATED_BY.
#
# ocpsvg is bounded for the same reason: it depends on the proxy directly and
# build123d's own bound on it is wide.
PIP_CONSTRAINTS = [
    "cadquery-ocp-proxy>=7.9,<8.0",
    "ocpsvg>=0.6,<0.7",
]


# pip treats an already-recorded distribution as satisfied and leaves its files
# alone, so re-asserting cadquery-ocp over a novtk install is a no-op without
# this.
#
# Deliberately without "--no-deps": the VTK-enabled OCP module is linked
# against VTK, so it fails to load at all ("libvtkWrappingPythonCore*.so:
# cannot open shared object file") unless the 'vtk' it depends on is installed
# alongside it. Skipping deps trades one broken sandbox for another.
FORCE_REINSTALL_FLAGS = ["--force-reinstall"]


def get_guard_path(path: str, python_package: str) -> str:
    """Path of the marker file recording that a package is installed."""
    python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
    return os.path.join(path, ".partcad.installed." + python_package_hash)


def get_reassert_path(path: str, python_package: str) -> str:
    """Path of the marker file demanding that a package be re-installed."""
    python_package_hash = hashlib.sha256(python_package.encode()).hexdigest()[:16]
    return os.path.join(path, ".partcad.reassert." + python_package_hash)


def invalidate_dependent_guards(path: str, python_package: str) -> None:
    """Flag the packages whose files this install has just overwritten.

    Installing build123d pulls 'cadquery-ocp-novtk', which writes the very same
    OCP native module as 'cadquery-ocp' and replaces it with a build compiled
    without VTK -- after which "import cadquery" fails inside the sandbox (see
    sandbox_versions.GUARD_INVALIDATED_BY).

    Dropping the install guard alone does not fix it: pip still considers
    'cadquery-ocp' satisfied and leaves the files alone. So a second marker is
    left behind to say the next install of that package has to be forced.
    """
    for clobbered in sandbox_versions.GUARD_INVALIDATED_BY.get(python_package, ()):
        with contextlib.suppress(OSError):
            os.remove(get_guard_path(path, clobbered))
        with contextlib.suppress(OSError):
            pathlib.Path(get_reassert_path(path, clobbered)).touch()


def needs_reassert(path: str, python_package: str) -> bool:
    """Whether this package has to be re-installed over a clobbered copy."""
    return os.path.exists(get_reassert_path(path, python_package))


def clear_reassert(path: str, python_package: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(get_reassert_path(path, python_package))


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
        # Must stay a warning, not an error. pc_logging.error() sets the global
        # had_errors flag that the CLI turns into a non-zero exit code, so
        # reporting a pre-existing conflict at error level fails runs that
        # otherwise pass. Whether the conflict is fatal is for the caller that
        # actually uses the environment to decide; this is only a diagnostic.
        pc_logging.warning("Dependency conflicts in %s:\n%s" % (path if path else self.path, report))

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
                    self.ensure_onced_locked(sandbox_versions.OCP_TESSELLATE)
                    self.ensure_onced_locked(sandbox_versions.NLOPT)
                    # CadQuery has no release for Python 3.10, and pip fails the
                    # whole install rather than skipping it. Nothing is lost by
                    # leaving it out: the factories that need CadQuery render on
                    # MIN_PYTHON_VERSION_CADQUERY or newer, so they never look at
                    # a 3.10 sandbox in the first place.
                    if sandbox_versions.is_at_least(self.version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY):
                        self.ensure_onced_locked(sandbox_versions.CADQUERY)
                    self.ensure_onced_locked(sandbox_versions.NUMPY)
                    self.ensure_onced_locked(sandbox_versions.TYPING_EXTENSIONS)
                    self.ensure_onced_locked(sandbox_versions.OCPSVG)
                    self.ensure_onced_locked(sandbox_versions.BUILD123D)
                    # Last: re-asserts the VTK-enabled OCP that build123d's
                    # 'cadquery-ocp-novtk' dependency has just replaced.
                    self.ensure_onced_locked(sandbox_versions.CADQUERY_OCP)
                    self.initialized = True

    async def once_async(self):
        async with self.async_lock():
            with self.sync_lock_install():
                if not self.initialized:
                    # Preinstall the most common packages to avoid
                    await self.ensure_async_onced_locked(sandbox_versions.OCP_TESSELLATE)
                    await self.ensure_async_onced_locked(sandbox_versions.NLOPT)
                    # See the note in once(): CadQuery has no Python 3.10 release.
                    if sandbox_versions.is_at_least(self.version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY):
                        await self.ensure_async_onced_locked(sandbox_versions.CADQUERY)
                    await self.ensure_async_onced_locked(sandbox_versions.NUMPY)
                    await self.ensure_async_onced_locked(sandbox_versions.TYPING_EXTENSIONS)
                    await self.ensure_async_onced_locked(sandbox_versions.OCPSVG)
                    await self.ensure_async_onced_locked(sandbox_versions.BUILD123D)
                    # Last: re-asserts the VTK-enabled OCP that build123d's
                    # 'cadquery-ocp-novtk' dependency has just replaced.
                    await self.ensure_async_onced_locked(sandbox_versions.CADQUERY_OCP)
                    self.initialized = True

    def _subprocess_env(self):
        """Environment for a spawned sandbox process, or None to inherit ours.

        The base runtime inherits the parent environment unchanged. Subclasses
        whose interpreter needs help locating its own shared libraries override
        this (see CondaPythonRuntime).
        """
        return None

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
                    env=self._subprocess_env(),
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
                #
                # Warning rather than error on purpose: pc_logging.error() sets
                # the global had_errors flag that becomes a non-zero exit code,
                # and the caller that consumes this exit code already reports
                # the failure itself. This line only explains why it happened.
                pc_logging.warning(
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
                    env=self._subprocess_env(),
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
                #
                # Warning rather than error on purpose: pc_logging.error() sets
                # the global had_errors flag that becomes a non-zero exit code,
                # and the caller that consumes this exit code already reports
                # the failure itself. This line only explains why it happened.
                pc_logging.warning(
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

    def ensure(self, python_package, session=None, path=None, force=False):
        self.once()
        self.ensure_onced(python_package, session=session, path=path, force=force)

    def ensure_onced(self, python_package, session=None, path=None, force=False):
        if path is None:
            path = self.path

        guard_path = get_guard_path(path, python_package)
        force = force or needs_reassert(path, python_package)
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
                                    *(FORCE_REINSTALL_FLAGS if force else []),
                                    python_package,
                                ],
                                path=path,
                            )
                        pathlib.Path(guard_path).touch()
                        clear_reassert(path, python_package)
                        invalidate_dependent_guards(path, python_package)
                invalidate_dependent_guards(path, python_package)

    def ensure_onced_locked(self, python_package, session=None, path=None, force=False):
        if path is None:
            path = self.path

        guard_path = get_guard_path(path, python_package)
        force = force or needs_reassert(path, python_package)
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
                            *(FORCE_REINSTALL_FLAGS if force else []),
                            python_package,
                        ],
                        path=path,
                    )
                pathlib.Path(guard_path).touch()
                clear_reassert(path, python_package)
                invalidate_dependent_guards(path, python_package)

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        await self.once_async()
        await self.ensure_async_onced(python_package, session=session, path=path, force=force)

    async def ensure_async_onced(self, python_package, session=None, path=None, force=False):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time
        guard_path = get_guard_path(path, python_package)
        force = force or needs_reassert(path, python_package)
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
                                    *(FORCE_REINSTALL_FLAGS if force else []),
                                    python_package,
                                ],
                                path=path,
                            )
                        pathlib.Path(guard_path).touch()
                        clear_reassert(path, python_package)
                        invalidate_dependent_guards(path, python_package)
                invalidate_dependent_guards(path, python_package)

    async def ensure_async_onced_locked(self, python_package, session=None, path=None, force=False):
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time

        guard_path = get_guard_path(path, python_package)
        force = force or needs_reassert(path, python_package)
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
                            *(FORCE_REINSTALL_FLAGS if force else []),
                            python_package,
                        ],
                        path=path,
                    )
                pathlib.Path(guard_path).touch()
                clear_reassert(path, python_package)
                invalidate_dependent_guards(path, python_package)

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
