#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandboxed Node.js environments, the JavaScript twin of runtime_python.

The shape of this module deliberately mirrors 'runtime_python': a runtime is a
Node.js of a given major version, packages are installed into it behind guard
files, a *session* collects the dependencies one PartCAD package needs, and the
whole thing is serialized by a runtime lock plus a per-environment file lock so
that concurrent PartCAD processes cannot install over each other.

What differs is the directory layout, because npm resolves dependencies from the
filesystem rather than from a path list. Three levels:

  <sandbox>/pc-js-<sandbox type>-<node major>/     the runtime
    env/                                           the baseline environment
      package.json                                 the manifest, carrying the npm overrides
      node_modules/                                what every sandbox gets by default
      .partcad.installed.<hash>                    install guards
      pkg-<package hash>/                          one working directory per PartCAD package
        node_modules -> ../node_modules            symlink, so cwd-based resolution works
        package.json -> ../package.json            symlink, so cwd-based detection works
    v-env-<dependency set hash>/                   an environment for one set of dependencies
      ... same contents as env/ ...

The middle level is the v-env twin: an npm dependency tree identified by the
*set of dependencies* it provides, so two PartCAD packages that declare the same
dependencies share one tree and a package that adds a dependency gets its own.
Nothing ever mutates a tree another package is depending on, which is what makes
it safe to share.

The third level exists because Node.js and npm both decide what to resolve from
the current working directory. Giving each PartCAD package its own directory
inside the environment - with the environment's 'node_modules' and
'package.json' symlinked in - means every run finds the right dependency tree
while whatever a run writes relative to that directory stays its own.

Containerized execution is inherited rather than reimplemented, exactly as
runtime_python inherits it: 'runtime.Runtime' owns 'use_docker()' and routes
'run()'/'run_async()' through the JSON-RPC client when one is attached, and the
provisioning path here (install_onced_locked) goes through those base methods
for the same reason the pip installs do. Running a wrapper spawns directly, as
runtime_python.run_onced does. Nothing in this module is docker-aware on its
own, and nothing should become so.
"""

import asyncio
import contextlib
import copy
import filecmp
import hashlib
import json
import os
import pathlib
import platform
import shutil
import signal
import subprocess
import threading

from filelock import FileLock

from . import sandbox_versions
from . import runtime
from . import logging as pc_logging
from . import telemetry

# The baseline environment, shared by every PartCAD package that needs nothing
# beyond the defaults. Named rather than hashed so it stays recognizable in
# a sandbox directory a user is looking at.
BASE_ENV_DIR = "env"

# Dependency versions forced onto the whole tree regardless of what a transitive
# dependency asks for, written into every environment's package.json as npm's
# "overrides". The pip-constraints twin (see runtime_python.PIP_CONSTRAINTS).
#
# Empty today: unlike OCP on the Python side, Chili3D's OCCT kernel is a
# WebAssembly module private to the 'chili3d' package, so two copies in one tree
# cannot clobber each other's native module - they simply do not share one. The
# mechanism is kept because the day a package does have to be bounded across a
# tree, the alternative is discovering it as an unexplained crash.
NPM_OVERRIDES: dict[str, str] = {}

# Installing a package on the left overwrites files owned by the packages on the
# right, which then have to be re-asserted. The npm twin of
# sandbox_versions.GUARD_INVALIDATED_BY, and empty for the same reason
# NPM_OVERRIDES is: npm gives each package its own directory. See
# invalidate_dependent_guards().
GUARD_INVALIDATED_BY: dict[str, tuple[str, ...]] = {}

# npm otherwise leaves a satisfied package alone, so re-asserting one over a
# clobbered copy needs to be forced.
FORCE_REINSTALL_FLAGS = ["--force"]


def get_guard_path(path: str, js_package: str) -> str:
    """Path of the marker file recording that a package is installed."""
    js_package_hash = hashlib.sha256(js_package.encode()).hexdigest()[:16]
    return os.path.join(path, ".partcad.installed." + js_package_hash)


def get_reassert_path(path: str, js_package: str) -> str:
    """Path of the marker file demanding that a package be re-installed."""
    js_package_hash = hashlib.sha256(js_package.encode()).hexdigest()[:16]
    return os.path.join(path, ".partcad.reassert." + js_package_hash)


def invalidate_dependent_guards(path: str, js_package: str) -> None:
    """Flag the packages whose files this install has just overwritten.

    The npm twin of runtime_python.invalidate_dependent_guards(): drop the
    install guard of every clobbered package and leave a second marker behind,
    because npm considers an already-recorded package satisfied and would not
    otherwise put its files back.
    """
    for clobbered in GUARD_INVALIDATED_BY.get(js_package, ()):
        with contextlib.suppress(OSError):
            os.remove(get_guard_path(path, clobbered))
        with contextlib.suppress(OSError):
            pathlib.Path(get_reassert_path(path, clobbered)).touch()


def needs_reassert(path: str, js_package: str) -> bool:
    """Whether this package has to be re-installed over a clobbered copy."""
    return os.path.exists(get_reassert_path(path, js_package))


def clear_reassert(path: str, js_package: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(get_reassert_path(path, js_package))


def env_dir_name(dependencies) -> str:
    """The environment directory for a set of dependencies.

    The identity is the *set*, not the order they were declared in: two packages
    that ask for the same dependencies get the same tree however their factories
    happened to sequence the requests. The baseline set gets the readable name
    so that the common case is obvious in a sandbox directory.
    """
    unique = sorted(set(dependencies))
    if not unique:
        return BASE_ENV_DIR
    digest = hashlib.sha256("\n".join(unique).encode()).hexdigest()[:16]
    return "v-env-" + digest


def package_dir_name(package_name: str) -> str:
    """The per-PartCAD-package working directory inside an environment."""
    return "pkg-" + hashlib.sha256(package_name.encode()).hexdigest()[:16]


def _requirement_list(requirements) -> list[str]:
    """Normalize a 'javascriptRequirements' value into a list of requirements.

    Accepts the list the schema describes and the newline-separated string the
    Python side also tolerates, and drops blank entries either way.
    """
    if requirements is None:
        return []
    if isinstance(requirements, str):
        requirements = requirements.strip().split("\n")
    return [requirement.strip() for requirement in requirements if requirement and requirement.strip()]


def package_requirements(project) -> list[str]:
    """What a package declares its Node.js sandbox needs.

    Module-level rather than a method on the runtime, like its Python twin:
    telemetry.instrument() rewrites every callable in a class body, and a
    'staticmethod' object is callable, so it would come back out as a plain
    function and turn into a bound method on the way through an instance.
    """
    return _requirement_list(project.config_obj.get("javascriptRequirements"))


def shape_requirements(config) -> list[str]:
    """What one shape declares its Node.js sandbox needs."""
    return _requirement_list(config.get("javascriptRequirements"))


def link_or_copy(source: str, destination: str) -> None:
    """Make 'destination' resolve to 'source', preferring a symlink.

    Node.js and npm find a dependency tree by walking up from the working
    directory, so the per-package directory needs the environment's
    'node_modules' and 'package.json' to appear inside it. A symlink is the
    cheap way to do that and is what every POSIX host gets.

    Windows only creates symlinks for a process that is elevated or has
    Developer Mode on, so falling back matters there: a directory falls back to
    a directory junction (which needs no privilege), and a file to a copy.

    A link or a junction always resolves to whatever the source holds now. A
    copy does not, so it is refreshed when the source has moved on - otherwise
    a package directory would keep a manifest the environment has since
    rewritten, and npm would resolve differently there than in the environment
    it belongs to.
    """
    if os.path.lexists(destination):
        if not os.path.islink(destination) and os.path.isfile(source) and os.path.isfile(destination):
            with contextlib.suppress(OSError):
                if not filecmp.cmp(source, destination, shallow=False):
                    shutil.copyfile(source, destination)
        return

    with contextlib.suppress(OSError, NotImplementedError):
        os.symlink(source, destination, target_is_directory=os.path.isdir(source))
        return

    if os.path.isdir(source):
        if os.name == "nt":
            # mklink /J - a junction, unlike a symlink, needs no privilege.
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", destination, source],
                    check=True,
                    capture_output=True,
                    shell=False,
                )
                return
        pc_logging.warning("Failed to link %s to %s" % (destination, source))
        return

    with contextlib.suppress(OSError):
        shutil.copyfile(source, destination)


class NodeEnvLock:
    """A file lock over one Node.js environment, the VenvLock twin."""

    lock: FileLock

    def __init__(self, runtime: "JavaScriptRuntime", env: str):
        # 'env' is the environment directory name, so the lock covers exactly
        # the tree that is about to be installed into or run from; two sessions
        # that share a tree share the lock, and two that do not, do not.
        if env is None:
            env = BASE_ENV_DIR
        env_lock_name = f".{runtime.sandbox_dir}.{env}.lock"
        # 'with' rather than acquire/release: 'env_locks_lock' is a plain Lock,
        # so anything raising in between would leave it held and block every
        # later construction in the process for good.
        with runtime.env_locks_lock:
            if env not in runtime.env_locks:
                runtime.env_locks[env] = FileLock(
                    os.path.join(runtime.ctx.user_config.internal_state_dir, env_lock_name), thread_local=False
                )
            self.lock = runtime.env_locks[env]

    def __enter__(self, *_args):
        self.lock.acquire()

    def __exit__(self, *_args):
        self.lock.release()


@telemetry.instrument()
class JavaScriptRuntime(runtime.Runtime):
    def __init__(self, ctx, sandbox, version=None):
        self.env_locks = {}
        self.env_locks_lock = threading.Lock()

        if version is None:
            version = sandbox_versions.DEFAULT_NODE_VERSION
        version = sandbox_versions.node_major_version(version)
        super().__init__(ctx, "js-" + sandbox + "-" + version)
        self.sandbox = sandbox
        self.version = version

        # Runtimes are meant to be executed from dedicated threads, outside of
        # the asyncio event loop. So a threading lock is appropriate here.
        self.lock = threading.RLock()
        self.tls = threading.local()

        # The path to the Node.js executable, and to npm
        self.exec_path = None
        self.npm_path = None
        # The names to search for in bin folders
        self.exec_name = "node" if os.name != "nt" else "node.exe"
        self.npm_name = "npm" if os.name != "nt" else "npm.cmd"

        # Keep the pipe clean: a wrapper's response is the last line of stdout
        # and any stderr is reported to the user, so Node's experimental-feature
        # notices would show up as spurious warnings on every single render.
        self.node_flags = ["--no-warnings"]

        self.npm_flags = ["--no-audit", "--no-fund", "--loglevel=error"]
        # '--save-exact' so what the manifest records is the version that was
        # installed, not the caret range npm would otherwise widen it to. The
        # exact versions here mean what pip's '==' does on the Python side, and
        # a later install into the same environment must not drift off them -
        # an environment is identified by the dependency set it holds, so the
        # set silently changing under it would make that identity a lie.
        self.npm_install_flags = ["--save-exact"]
        if platform.system() == "Windows":
            # npm otherwise fails an install whose dependency tree contains a
            # path longer than the legacy limit, which node_modules easily does.
            self.npm_install_flags += ["--no-bin-links"]

    #
    # Sandbox layout
    #

    def get_env_path(self, session=None, path=None):
        """The environment (v-env twin) a run or an install uses."""
        if path is not None:
            return path
        if session is None or not session["dirty"]:
            return os.path.join(self.path, BASE_ENV_DIR)
        return os.path.join(self.path, env_dir_name(session["deps"]))

    def get_package_path(self, session=None, path=None):
        """The per-PartCAD-package working directory inside that environment.

        This is the directory Node.js is launched in. Without a session there is
        no PartCAD package to isolate - that is PartCAD's own bookkeeping, such
        as asking Node for its version - so the environment itself is used.
        """
        env_path = self.get_env_path(session, path)
        if session is None:
            return env_path
        return os.path.join(env_path, package_dir_name(session["name"]))

    def prepare_env_locked(self, env_path: str) -> None:
        """Make sure an environment directory has the manifest npm needs.

        Without a package.json npm walks up looking for an enclosing project and
        installs into that instead, so the manifest has to exist before anything
        is installed. It is also where the overrides live.

        The fields PartCAD owns are merged into whatever manifest is already
        there rather than replacing it. npm records each install under
        "dependencies" in this very file, and rewriting the file from scratch
        would drop those - after which the next 'npm install' treats the
        packages as no longer wanted and prunes them from the tree.
        """
        os.makedirs(env_path, exist_ok=True)
        manifest_path = os.path.join(env_path, "package.json")

        existing = {}
        try:
            with open(manifest_path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            pass

        manifest = dict(existing)
        manifest.update(
            {
                "name": "partcad-sandbox",
                "version": "1.0.0",
                "private": True,
                # The wrappers and the scripts they run are ES modules.
                "type": "module",
            }
        )
        if NPM_OVERRIDES:
            manifest["overrides"] = dict(NPM_OVERRIDES)
        elif "overrides" in manifest:
            del manifest["overrides"]

        if manifest == existing:
            return

        try:
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
                f.write("\n")
        except OSError as e:
            # Not being able to write the manifest is not fatal on its own: npm
            # can still install, it just loses the overrides. Warn loudly rather
            # than failing the render.
            pc_logging.warning("Failed to write %s: %s" % (manifest_path, e))

    def prepare_package_dir_locked(self, session=None, path=None) -> str:
        """Create the per-package working directory and link the tree into it."""
        env_path = self.get_env_path(session, path)
        package_path = self.get_package_path(session, path)
        if package_path == env_path:
            return package_path

        os.makedirs(package_path, exist_ok=True)
        # 'node_modules' first: it is what resolution actually needs, and it is
        # the one that must be a link rather than a copy.
        link_or_copy(os.path.join(env_path, "node_modules"), os.path.join(package_path, "node_modules"))
        link_or_copy(os.path.join(env_path, "package.json"), os.path.join(package_path, "package.json"))
        return package_path

    #
    # Locking
    #

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
    def sync_lock(self, session=None, path=None):
        """Lock the runtime and the environment for executing a command

        'path' names the environment directly, for the callers that install
        into one the session does not point at. Without it the lock would cover
        the baseline while the work happened somewhere else, and since
        'self.lock' is process-local that would leave two processes free to run
        npm against the same tree.
        """
        with self.lock:
            env = os.path.basename(self.get_env_path(session, path))
            with NodeEnvLock(self, env):
                yield

    @contextlib.asynccontextmanager
    async def async_lock(self, session=None, path=None):
        """Lock the runtime and the environment for executing a command

        See sync_lock() for what 'path' is for.
        """
        async with self.get_async_lock():
            with self.lock:
                env = os.path.basename(self.get_env_path(session, path))
                with NodeEnvLock(self, env):
                    yield

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        """Lock the runtime and the environment for installation of packages"""
        yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        """Lock the runtime and the environment for installation of packages"""
        yield

    #
    # Initialization
    #

    def once(self):
        """Provision the baseline environment: the default stack, nothing else.

        The defaults are re-asserted on every call rather than only when the
        sandbox is new. 'initialized' is set from the mere existence of the
        sandbox directory, so a sandbox provisioned by an earlier PartCAD would
        otherwise never be told about a package the defaults have since gained.
        The install guards make this one stat() per package once it has run -
        the same trade runtime_python makes for zstd.
        """
        with self.sync_lock():
            with self.sync_lock_install():
                if not self.initialized:
                    self.prepare_env_locked(os.path.join(self.path, BASE_ENV_DIR))
                    self.initialized = True
                for js_package in sandbox_versions.DEFAULT_JS_REQUIREMENTS:
                    self.ensure_onced_locked(js_package)

    async def once_async(self):
        """Asynchronous counterpart of once()."""
        async with self.async_lock():
            with self.sync_lock_install():
                if not self.initialized:
                    self.prepare_env_locked(os.path.join(self.path, BASE_ENV_DIR))
                    self.initialized = True
                for js_package in sandbox_versions.DEFAULT_JS_REQUIREMENTS:
                    await self.ensure_async_onced_locked(js_package)

    def _subprocess_env(self):
        """Environment for a spawned sandbox process, or None to inherit ours.

        The base runtime inherits the parent environment unchanged. Subclasses
        whose Node.js needs help locating its own shared libraries override this
        (see CondaJavaScriptRuntime).
        """
        return None

    def get_node_path(self):
        """The Node.js executable this runtime runs scripts with."""
        if self.exec_path is not None:
            return self.exec_path
        return os.path.join(self.path, "bin", self.exec_name)

    def get_npm_path(self):
        """The npm executable this runtime installs packages with."""
        if self.npm_path is not None:
            return self.npm_path
        return os.path.join(self.path, "bin", self.npm_name)

    #
    # Running
    #

    def run(self, cmd, stdin="", cwd=None, session=None):
        self.once()
        return self.run_onced(cmd, stdin=stdin, cwd=cwd, session=session)

    def run_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        # Hold the environment-scoped lock across BOTH provisioning and
        # execution, for the same reason runtime_python.run_onced() does: a
        # session's installs and the run that depends on them have to be one
        # critical section, or a concurrent install into the same tree can be
        # half-done at the moment Node.js starts resolving from it.
        with self.sync_lock(session):
            self.provision_onced_locked(session)
            return self.execute_onced_locked(cmd, stdin=stdin, cwd=cwd, session=session, path=path)

    def run_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        self.provision_onced_locked(session)
        return self.execute_onced_locked(cmd, stdin=stdin, cwd=cwd, session=session, path=path)

    async def run_async(self, cmd, stdin="", cwd=None, session=None):
        await self.once_async()
        return await self.run_async_onced(cmd, stdin=stdin, cwd=cwd, session=session)

    async def run_async_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        # See the note in run_onced(): install and run are one critical section.
        async with self.async_lock(session):
            await self.provision_async_onced_locked(session)
            return await self.execute_async_onced_locked(cmd, stdin=stdin, cwd=cwd, session=session, path=path)

    async def run_async_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        await self.provision_async_onced_locked(session)
        return await self.execute_async_onced_locked(cmd, stdin=stdin, cwd=cwd, session=session, path=path)

    def provision_onced_locked(self, session=None):
        """Materialize the environment a dirty session needs."""
        if not session or not session["dirty"]:
            return
        env_path = self.get_env_path(session)
        if not os.path.exists(env_path):
            with pc_logging.Action("v-env", self.version, session["name"]):
                pc_logging.debug("Creating a Node.js environment: %s" % env_path)
                self.prepare_env_locked(env_path)
        with self.sync_lock_install():
            for dep in session["deps"]:
                self.ensure_onced_locked(dep, path=env_path)

    async def provision_async_onced_locked(self, session=None):
        """Asynchronous counterpart of provision_onced_locked()."""
        if not session or not session["dirty"]:
            return
        env_path = self.get_env_path(session)
        if not os.path.exists(env_path):
            with pc_logging.Action("v-env", self.version, session["name"]):
                pc_logging.debug("Creating a Node.js environment: %s" % env_path)
                self.prepare_env_locked(env_path)
        with self.sync_lock_install():
            for dep in session["deps"]:
                await self.ensure_async_onced_locked(dep, path=env_path)

    def build_command(self, cmd, cwd=None, session=None, path=None):
        """The argv to spawn, and the working directory to spawn it in.

        Node.js starts in the sandbox's per-package directory unless the caller
        names another one, so that a bare import resolves against the sandbox's
        dependency tree rather than against whatever happens to sit above the
        user's package. The directory a *script* is meant to see travels
        separately, as an argument the wrapper changes to once the CAD stack is
        loaded - exactly how the Python wrappers take theirs.
        """
        package_path = self.prepare_package_dir_locked(session, path)
        return [self.get_node_path(), *self.node_flags, *cmd], (cwd if cwd is not None else package_path)

    def execute_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        argv, package_path = self.build_command(cmd, cwd, session, path)
        pc_logging.debug("Running: %s (in %s)", argv, package_path)
        with telemetry.start_as_current_span("JavaScriptRuntime.execute_onced_locked.*{subprocess.Popen}") as span:
            # Strip user home directory from the path, if any
            sanitized_cmd = copy.copy(argv)
            sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
            span.set_attribute("cmd", " ".join(sanitized_cmd))
            p = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._subprocess_env(),
                cwd=package_path,
            )
            stdout, stderr = p.communicate(input=stdin.encode())

        return self._finish(argv, p.returncode, stdout.decode(), stderr.decode(), package_path)

    async def execute_async_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        argv, package_path = self.build_command(cmd, cwd, session, path)
        pc_logging.debug("Running: %s (in %s)", argv, package_path)
        with telemetry.start_as_current_span(
            "JavaScriptRuntime.execute_async_onced_locked.*{subprocess.Popen}"
        ) as span:
            # Strip user home directory from the path, if any
            sanitized_cmd = copy.copy(argv)
            sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
            span.set_attribute("cmd", " ".join(sanitized_cmd))
            p = await asyncio.create_subprocess_exec(
                *argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._subprocess_env(),
                cwd=package_path,
            )
            stdout, stderr = await p.communicate(input=stdin.encode())

        return self._finish(argv, p.returncode, stdout.decode(), stderr.decode(), package_path)

    def _finish(self, cmd, returncode, stdout, stderr, path):
        """Log what a Node.js process produced and normalize its exit code."""
        if stdout:
            pc_logging.debug("Output of %s: %s" % (cmd, stdout))
        if stderr:
            if returncode == 0:
                pc_logging.warning("%s produced stderr: %s" % (cmd, stderr))
                stderr = ""
            else:
                pc_logging.error("Error in %s: %s" % (cmd, stderr))

        if returncode != 0 and not stdout and not stderr:
            # A Node.js process that dies without writing anything at all is
            # almost always the WebAssembly kernel running out of memory, which
            # produces no JavaScript exception to catch. Say so here; the caller
            # that consumes the exit code reports the failure itself, so this is
            # a warning rather than an error (pc_logging.error() sets the global
            # had_errors flag that becomes a non-zero process exit code).
            pc_logging.warning(
                "%s terminated abnormally (%s) without any output. This usually means the WebAssembly "
                "CAD kernel ran out of memory, in %s" % (cmd, runtime_exit_description(returncode), path)
            )

        return returncode, stdout, stderr

    #
    # Installing
    #

    def npm_install_command(self, js_package, path, force=False):
        return [
            self.get_npm_path(),
            "install",
            *self.npm_flags,
            *self.npm_install_flags,
            *(FORCE_REINSTALL_FLAGS if force else []),
            "--prefix",
            path,
            js_package,
        ]

    def install_onced_locked(self, js_package, path, force=False):
        """Run the npm install of one package into one environment."""
        self.prepare_env_locked(path)
        with pc_logging.Action("NpmInst", self.version, js_package + " in " + path):
            # Through the base Runtime, which is what carries the (unfinished)
            # remote/containerized execution path; npm is a Node.js script but
            # is spawned by its own launcher, not by this runtime's Node.js.
            exitcode, _, stderr = super().run(self.npm_install_command(js_package, path, force), stdin="", cwd=path)
        if exitcode != 0:
            pc_logging.error("Failed to install %s into %s: %s" % (js_package, path, stderr))
            return
        pathlib.Path(get_guard_path(path, js_package)).touch()
        clear_reassert(path, js_package)
        invalidate_dependent_guards(path, js_package)

    async def install_async_onced_locked(self, js_package, path, force=False):
        """Asynchronous counterpart of install_onced_locked()."""
        self.prepare_env_locked(path)
        with pc_logging.Action("NpmInst", self.version, js_package + " in " + path):
            exitcode, _, stderr = await super().run_async(
                self.npm_install_command(js_package, path, force), stdin="", cwd=path
            )
        if exitcode != 0:
            pc_logging.error("Failed to install %s into %s: %s" % (js_package, path, stderr))
            return
        pathlib.Path(get_guard_path(path, js_package)).touch()
        clear_reassert(path, js_package)
        invalidate_dependent_guards(path, js_package)

    def ensure(self, js_package, session=None, path=None, force=False, default=False):
        self.once()
        self.ensure_onced(js_package, session=session, path=path, force=force, default=default)

    def ensure_onced(self, js_package, session=None, path=None, force=False, default=False):
        if session:
            self.declare_dependency(session, js_package, default=default)
            return
        if path is None:
            path = os.path.join(self.path, BASE_ENV_DIR)
        with self.sync_lock(path=path):
            with self.sync_lock_install():
                if not os.path.exists(get_guard_path(path, js_package)):
                    self.install_onced_locked(js_package, path, force or needs_reassert(path, js_package))

    def ensure_onced_locked(self, js_package, session=None, path=None, force=False, default=False):
        if session:
            self.declare_dependency(session, js_package, default=default)
            return
        if path is None:
            path = os.path.join(self.path, BASE_ENV_DIR)
        if not os.path.exists(get_guard_path(path, js_package)):
            self.install_onced_locked(js_package, path, force or needs_reassert(path, js_package))

    async def ensure_async(self, js_package, session=None, path=None, force=False, default=False):
        await self.once_async()
        await self.ensure_async_onced(js_package, session=session, path=path, force=force, default=default)

    async def ensure_async_onced(self, js_package, session=None, path=None, force=False, default=False):
        if session:
            self.declare_dependency(session, js_package, default=default)
            return
        if path is None:
            path = os.path.join(self.path, BASE_ENV_DIR)
        async with self.async_lock(path=path):
            with self.sync_lock_install():
                if not os.path.exists(get_guard_path(path, js_package)):
                    await self.install_async_onced_locked(js_package, path, force or needs_reassert(path, js_package))

    async def ensure_async_onced_locked(self, js_package, session=None, path=None, force=False, default=False):
        if session:
            self.declare_dependency(session, js_package, default=default)
            return
        if path is None:
            path = os.path.join(self.path, BASE_ENV_DIR)
        if not os.path.exists(get_guard_path(path, js_package)):
            await self.install_async_onced_locked(js_package, path, force or needs_reassert(path, js_package))

    def declare_dependency(self, session, js_package, default=False):
        """Add a dependency to a session, replacing any other ask for that package.

        Uniqueness is by npm package name, not by the whole requirement string:
        a tree holding both 'chili3d@1.1.2' and 'chili3d@1.0.0' is not a thing
        npm can produce, so the two have to resolve to one. 'default=True' marks
        a requirement PartCAD supplies on its own behalf - it yields to anything
        the package or the part named, whichever order they arrive in - while an
        explicit declaration replaces whatever came before it. That ordering is
        what makes a part's 'chili3dVersion' win over its package's, which wins
        over a 'chili3d@...' listed in 'javascriptRequirements'.

        Whether a session needs an environment of its own is then derived from
        the result rather than tracked as it goes, so a declaration that happens
        to restate a default leaves the session on the shared baseline.
        """
        name = sandbox_versions.js_package_name(js_package)
        for index, declared in enumerate(session["deps"]):
            if sandbox_versions.js_package_name(declared) != name:
                continue
            if default or declared == js_package:
                return
            session["deps"][index] = js_package
            break
        else:
            session["deps"].append(js_package)

        session["dirty"] = set(session["deps"]) != set(sandbox_versions.DEFAULT_JS_REQUIREMENTS)

    def declare_requirements(self, session, requirements, default=False):
        """Declare several dependencies at once, in the order given."""
        for requirement in requirements:
            self.declare_dependency(session, requirement, default=default)

    #
    # Dependency declarations
    #
    # Unlike the Python side, these are resolved when a factory is constructed
    # rather than when a part is rendered, and they are plain functions because
    # nothing here touches the network - installing is what
    # provision_async_onced_locked() does, from the set these produce.
    #
    # Settling the set up front is what lets an environment be identified by it:
    # the directory a part renders in, and the cache key its shape is stored
    # under, are both derived from the set and so must not still be moving when
    # the render starts.
    #

    def get_session(self, name: str):
        """Create a context describing the environment this package needs.

        Seeded with the default stack rather than left empty, so that a session
        which later declares a dependency of its own gets an environment
        carrying the whole set - the baseline packages included - instead of one
        holding only the extra.
        """
        return {
            "name": name,
            "hash": hashlib.sha256(name.encode()).hexdigest()[:16],
            "dirty": False,
            "deps": list(sandbox_versions.DEFAULT_JS_REQUIREMENTS),
        }


def runtime_exit_description(returncode: int) -> str:
    """Describe a Node.js exit code, naming the signal if it was killed by one."""
    if returncode is not None and returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = "unknown signal"
        return "killed by signal %d (%s)" % (-returncode, name)
    if returncode == 134:
        # What an Emscripten abort() looks like once the shell has translated it
        return "exit code 134 (SIGABRT, usually a WebAssembly abort)"
    return "exit code %s" % returncode
