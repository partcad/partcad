#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import contextlib
import copy
import importlib
import os
import shutil
import subprocess
import sys
import json

from . import runtime_python
from . import sandbox_lock
from . import sandbox_versions
from . import logging as pc_logging
from . import telemetry

# Conda/mamba failures that are the machine, not the request, and that a retry
# has been observed to clear. Matched against the stderr of "conda create".
#
# "Unexpected error N on netlink descriptor M" is not conda's own message at
# all: it is glibc's, from check_pf.c, where getaddrinfo() enumerates local
# interfaces over a NETLINK_ROUTE socket. When that socket answers with an
# unexpected errno (9 is EBADF), glibc calls __libc_fatal() and kills the
# process outright -- so conda dies mid-solve, through no fault of its own or
# ours, and leaves no prefix behind. It is a property of the runner's network
# namespace and it comes and goes; the retry below is the whole remedy.
_SPORADIC_CONDA_ERRORS = (
    "Found incorrect download",
    "libmamba libarchive",
    "netlink descriptor",
)

# The subset of the above that says the *package cache* is what is broken, not
# the request: a tarball that did not survive its download, or an extracted
# directory that cannot be read back. Retrying is futile while the bad entry is
# still cached -- the next solve finds the same file and fails identically,
# which is exactly what happened on ubuntu-24.04-arm64 in run 33293181928:
#
#   warning  libmamba Extracted package cache '.../pycairo-1.29.1-py311hbe9a378_0'
#            has invalid 'repodata_record.json' file: [json.exception...]
#   error    libmamba Error when extracting package: filesystem error:
#            cannot remove all: Bad file descriptor [.../pycairo-...]
#   Found incorrect download: pycairo. Aborting
#
# Both attempts failed with the same message, three minutes apart. The remedy
# is to drop the cache before the retry, which is what _clean_package_cache()
# below does.
_CORRUPT_CONDA_CACHE_ERRORS = (
    "Found incorrect download",
    "repodata_record.json",
    "Error when extracting package",
)


def _is_corrupt_cache(stderr: str) -> bool:
    """Whether this failure means the shared package cache is unusable."""
    return any(marker in stderr for marker in _CORRUPT_CONDA_CACHE_ERRORS)


@telemetry.instrument()
class CondaPythonRuntime(runtime_python.PythonRuntime):
    # The last thing that went wrong while provisioning this sandbox. Every
    # diagnostic inside an attempt is a warning, because the attempt may be
    # retried; this is what the exception raised after the last attempt quotes,
    # so that the fatal message names the cause and not just the fact. A class
    # attribute so that it is readable however the instance was made.
    conda_last_error = None

    def __init__(self, ctx, version=None, variant=None):
        if variant is None:
            sandbox_type_name = "conda"
            self.variant_packages = []
        else:
            sandbox_type_name = f"conda-{variant}"
            self.variant_packages = [f"{variant}"]
        super().__init__(ctx, sandbox_type_name, version)

        # One object for the whole process, shared with every other conda
        # sandbox -- the Python ones of the other versions and the Node.js
        # one (see sandbox_lock.conda).
        self.global_conda_lock = sandbox_lock.conda(ctx.user_config.internal_state_dir)
        self.conda_initialized = self.initialized
        # Set by verify_conda() when the sandbox on disk turns out to hold a
        # free-threaded interpreter, which nothing but a rebuild can fix.
        self.conda_free_threaded = False

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

    def python_abi_specs(self):
        """The specs holding every solve in this prefix to the GIL interpreter.

        Every conda command that touches the prefix has to carry these, not just
        the "create". A solve is free to replace what a previous one installed,
        and an unconstrained one does: creating with the ABI pinned and then
        running a plain "conda install pip pycairo" swapped the interpreter out
        from under the sandbox for the free-threaded build of the same version --

            UNLINK python 3.14.0 h32b2ec7_103_cp314
            LINK   python 3.14.6 hf9ea5aa_1_cp314t

        which is how a sandbox created with the pin still ended up free-threaded.
        The two builds are the same version with the same build number, so
        nothing but this spec decides which one a tie goes to.

        Empty below 3.13, where CPython has no free-threaded build to
        disambiguate. See sandbox_versions.python_abi_requirement().
        """
        python_abi = sandbox_versions.python_abi_requirement(self.version, exact=self.is_mamba)
        return [] if python_abi is None else [python_abi]

    def discard_prefix(self):
        """Remove the sandbox prefix and forget everything that described it.

        The install guards are marker files inside the prefix, so they go with
        it. What does not is what this object remembers: 'initialized' was read
        off the prefix existing (see runtime.Runtime), and 'constraints_path' is
        memoized on first use. Left alone, the rebuilt prefix would be handed a
        constraints file that no longer exists -- "Could not open constraint
        file" on every install into it -- and would never be given the CAD stack,
        because once() skips that whole block when 'initialized' is set.
        """
        shutil.rmtree(self.path, ignore_errors=True)
        self.initialized = False
        self.conda_initialized = False
        self.constraints_path = None

    def discard_if_free_threaded(self):
        """Throw the prefix away if it holds a free-threaded interpreter.

        Only ever true for a sandbox whose interpreter has no CAD wheels at all
        (see verify_conda). Every other verify failure leaves the prefix where it
        is, as before, for the next attempt to install into.
        """
        if not self.conda_free_threaded:
            return
        self.discard_prefix()
        self.conda_free_threaded = False

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
                elif "free-threading" in stdout:
                    # A sandbox built before the ABI was pinned can hold the
                    # free-threaded interpreter, and the version check above
                    # waves it through: sys.version reads "3.14.0 free-threading
                    # build (...)", so it starts with "3.14" like any other. The
                    # sandbox directory is named after the version alone
                    # (pc-py-conda-3.14), so there is nothing else to tell the
                    # two apart either. Left alone it would keep failing every
                    # script-defined part with "No module named 'OCP'" forever,
                    # since no CAD wheel is built for that ABI. Rebuild it
                    # instead - this is the one case where the existing prefix
                    # has to go, so 'conda create' has somewhere to create into.
                    pc_logging.warning("conda venv is a free-threaded build, rebuilding it: %s" % stdout.strip())
                    self.conda_free_threaded = True
                    self.conda_initialized = False
                else:
                    self.conda_initialized = True
            except Exception as e:
                pc_logging.warning("conda venv check error: %s" % e)
                self.conda_initialized = False

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        with self.global_conda_lock.acquire(write=True):
            yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        """The asynchronous twin of sync_lock_install().

        Not 'with self.global_conda_lock.acquire(...)': conda runs for minutes
        and this lock is held across the 'await's that wait for it, so a task
        that waited for it by blocking would be blocking the loop the holder
        needs in order to finish and release.
        """
        async with self.global_conda_lock.acquire_async(write=True):
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
        # 'provisioned' is raised by the base implementation below, once the
        # whole of this has run. Without the check, every command run in this
        # sandbox re-entered once_conda_locked(), which spawns an interpreter
        # to ask the prefix what version it is (see verify_conda) -- an extra
        # process per requirement checked and per file rendered.
        if self.provisioned:
            return
        with self.sync_lock(write=True):
            self.once_conda_locked()
        super().once()

    async def once_async(self):
        if self.provisioned:
            return
        async with self.async_lock(write=True):
            await self.once_conda_locked_async()
        await super().once_async()

    def once_conda_locked(self):
        with self.sync_lock_install():
            self.once_conda_holding_install_lock()

    async def once_conda_locked_async(self):
        """once_conda_locked() for a caller that is running on an event loop.

        Only the wait for the conda lock is asynchronous. What happens under it
        is the same synchronous conda run: it spawns processes and waits for
        them, and giving it an asynchronous form is a separate change (see the
        TODO on once_conda_locked_attempt).
        """
        async with self.async_lock_install():
            self.once_conda_holding_install_lock()

    def once_conda_holding_install_lock(self):
        """Create the conda prefix. The conda lock is already held."""
        # See if it just got created
        if os.path.exists(self.path):
            self.verify_conda()
            self.discard_if_free_threaded()

        # TODO(clairbee): Does it make sense to retry more than once?
        attempts = 0
        while not self.conda_initialized and attempts < 2:
            # Sometimes it fails to create from the first attempt
            attempts += 1
            self.once_conda_locked_attempt()
            if self.conda_initialized:
                # An attempt reports success from the exit code of the last
                # command it ran, which says nothing about *which*
                # interpreter ended up in the prefix. Ask the prefix itself,
                # so a create that quietly produced the wrong one is caught
                # here rather than by the next process to open this sandbox
                # -- which is what turned this into a rebuild every sandbox
                # of every run repeated and none of them fixed.
                self.verify_conda()
                self.discard_if_free_threaded()

        if not self.conda_initialized:
            # The one fatal point in provisioning, and the only place that gets
            # to fail the run. Everything an attempt logged on the way here was
            # a warning, so this message has to carry the cause: a bare
            # "initialization failed" from a command that then went on to render
            # everything successfully is what made this unactionable in CI.
            raise Exception(
                "ERROR: Conda environment initialization failed for Python %s at %s after %d attempt(s): %s"
                % (
                    self.version,
                    self.path,
                    attempts,
                    self.conda_last_error or "no diagnostic was captured",
                )
            )

    def _clean_package_cache(self):
        """Drop conda's shared package cache, best effort.

        Called only when a failure names the cache itself (see
        ``_is_corrupt_cache``). The cache is shared by every environment conda
        manages on this machine, so this is not free -- the next solve
        re-downloads what it needs -- but a corrupt entry is not repaired by
        anything cheaper, and it fails every environment that wants that
        package, not just this one.

        Never fatal. It runs while an attempt is already failing, so the worst
        it can do is leave the caller exactly where it was; a cleanup that
        raised, or that hung, would replace a recoverable failure with a worse
        one. Hence the bounded wait and the blanket except.
        """
        args = [self.conda_path, "clean", "--packages", "--tarballs", "-y"]
        try:
            with telemetry.start_as_current_span("CondaPythonRuntime._clean_package_cache"):
                p = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    encoding="utf-8",
                )
                _, stderr = p.communicate(timeout=300)
            if p.returncode != 0:
                pc_logging.warning("conda clean exited %s: %s" % (p.returncode, (stderr or "").strip()))
            else:
                pc_logging.warning("Dropped the conda package cache after a corrupt entry; it will be refetched")
        except Exception as e:
            pc_logging.warning("conda clean failed: %s" % e)

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
                            # "=" rather than "=="; the two do not mean the same
                            # thing here. libmamba reads "python==3.14" as the
                            # 3.14 release exactly, which is 3.14.0 -- so the
                            # mamba branch this used to have pinned every sandbox
                            # to the oldest patch of its line, and left the next
                            # solve wanting to upgrade it. "=3.14" is the fuzzy
                            # "3.14.*" both conda and mamba mean by it.
                            "python=%s" % self.version,
                            # The python spec above names a version and nothing
                            # else, which from 3.13 on leaves the solver free to
                            # pick the free-threaded (no-GIL) build of it -- and
                            # it does. No CAD wheel exists for that ABI, so pin
                            # the GIL one.
                            *self.python_abi_specs(),
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
                        stdout, stderr = p.communicate()

                    # Everything reported in here is a *warning*, however bad it
                    # reads. This is one attempt of several, and whether the
                    # sandbox ends up usable is decided by the caller
                    # (once_conda_holding_install_lock), which retries and then
                    # raises. pc_logging.error() sets the global had_errors flag
                    # that the CLI turns into a non-zero exit at the very end of
                    # the command -- so an error logged here failed a run that
                    # had already recovered, rendered everything and finished.
                    if not stderr is None and stderr.strip() != "":
                        self.conda_last_error = stderr.strip()
                        # Handle most common sporadic conda/mamba failures
                        if any(marker in stderr for marker in _SPORADIC_CONDA_ERRORS):
                            pc_logging.warning("conda env install error (retrying): %s" % stderr)
                            # A retry against the same broken cache reproduces
                            # the same failure, so drop it first.
                            if _is_corrupt_cache(stderr):
                                self._clean_package_cache()
                            attempts += 1
                            continue
                        pc_logging.warning("conda env install error: %s" % stderr)
                    elif p.returncode != 0:
                        # A failed solve under "--json" is reported *on stdout*,
                        # as {"success": false, "error": ...}, and leaves stderr
                        # empty -- so the check above sees a clean run and this
                        # one is the only thing between a failed create and the
                        # "conda install" below being asked to populate a prefix
                        # that was never made.
                        self.conda_last_error = "conda env create exited %s: %s" % (
                            p.returncode,
                            (stdout or "").strip(),
                        )
                        pc_logging.warning(
                            "conda env create failed (exit %s): %s" % (p.returncode, (stdout or "").strip())
                        )
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
                        # Not redundant with the "create" above: this solve is
                        # free to replace the interpreter that one installed, and
                        # without this it does. See python_abi_specs().
                        *self.python_abi_specs(),
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
                    # A warning for the same reason as the create diagnostics
                    # above: this only means *this* attempt did not finish, and
                    # the caller decides whether that is fatal.
                    self.conda_last_error = "conda pip install exited %s: %s" % (
                        p.returncode,
                        (stderr or "").strip(),
                    )
                    pc_logging.warning("conda pip install return code: %s" % p.returncode)
                    # This half of the attempt had no equivalent of the create
                    # loop's sporadic-error handling, so a corrupt cache here
                    # was retried by the caller against the very same cache and
                    # failed the same way both times. Dropping it makes the
                    # caller's next attempt a different attempt rather than a
                    # repeat of this one. Only the cache is cleaned -- whether
                    # the failure is fatal stays the caller's call.
                    if _is_corrupt_cache(stderr or ""):
                        self._clean_package_cache()
                    self.conda_initialized = False
                else:
                    self.conda_initialized = True
            except Exception as e:
                self.discard_prefix()
                raise e
