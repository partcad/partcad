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
import subprocess
import sys

from . import logging as pc_logging
from . import runtime, sandbox_lock, sandbox_versions, telemetry
from .process_crash import describe_exit_code, describe_termination, killed_by_signal  # noqa: F401  (re-exported)
from .process_output import answer as stdout_of
from .process_output import decode as decode_output
from .process_output import loggable

# A sandbox is layered. Its own environment -- the conda prefix, the venv, the
# image's interpreter -- holds what nearly every wrapper imports (see
# base_requirements) and is written only while the sandbox is first provisioned.
# Anything a run needs beyond that goes into a *layer*: a v-env inside the
# sandbox that sees the base's site-packages through a .pth file, after its own,
# so a layer carries only what differs from the base and anything it installs
# comes first. A layer is named after what it adds, so every run asking for the
# same additions shares one; it is written only while it is being provisioned,
# and read by any number of runs at once afterwards.
#
# Why not '--system-site-packages': a v-env made by an interpreter that is
# itself a venv's -- the 'venv' and 'docker' sandboxes -- would see the system
# interpreter's site-packages through it rather than the sandbox's.
#
# Every layer directory is named this way, which is what lets the environment
# lock recover the layer's hash from the path alone.
VENV_PREFIX = "v-env-"

# The file in a layer's site-packages that puts the base's site-packages on
# sys.path after the layer's own.
LAYER_PTH = "_partcad_base.pth"

# The guard recording that a layer has been linked to its base -- written once
# LAYER_PTH is, so a layer whose creation was interrupted is linked again.
LAYER_GUARD = "partcad:layer"

# What the base's own interpreter is asked for the directories its packages are
# in: the ones a layer has to see.
BASE_SITE_DIRS_COMMAND = (
    "-c",
    "import sysconfig; print(sysconfig.get_path('purelib')); print(sysconfig.get_path('platlib'))",
)

# Run by a layer's interpreter, with the base's directories as its arguments:
# writes LAYER_PTH where that interpreter keeps its own packages. Run there
# rather than written from here because only the layer's interpreter knows where
# that is -- in the 'docker' sandbox it is a path inside the container.
LINK_LAYER_COMMAND = (
    "-c",
    "import pathlib, sys, sysconfig; "
    "pathlib.Path(sysconfig.get_path('purelib'), %r).write_text('\\n'.join(sys.argv[1:]) + '\\n')" % LAYER_PTH,
)


def read_site_dirs(exitcode, stdout, stderr) -> list:
    """The base's package directories, from what BASE_SITE_DIRS_COMMAND printed, each once."""
    site_dirs = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line and line not in site_dirs:
            site_dirs.append(line)
    if exitcode != 0 or not site_dirs:
        raise Exception(
            "Failed to find where the sandbox keeps its packages: %s"
            % ((stderr or "").strip() or "exit code %s" % exitcode)
        )
    return site_dirs


def layer_created(path, exitcode, stderr) -> None:
    """Fail with what went wrong when '-m venv' did not build a layer."""
    if exitcode != 0:
        raise Exception(
            "Failed to create the layer %s: %s" % (path, (stderr or "").strip() or "exit code %s" % exitcode)
        )


def layer_linked(path, exitcode, stderr) -> None:
    """Record that a layer sees its base, or fail with why it does not."""
    if exitcode != 0:
        raise Exception(
            "Failed to link the layer %s to its sandbox: %s"
            % (path, (stderr or "").strip() or "exit code %s" % exitcode)
        )
    pathlib.Path(get_guard_path(path, LAYER_GUARD)).touch()


# Part of every Python sandbox's directory name. A sandbox provisioned before
# sandboxes were layered holds CadQuery's OCP in its own environment and was
# written to by every render; it is left as it is -- a PartCAD of that release
# may still be running out of it -- and the layered one is built beside it.
SANDBOX_LAYOUT = "layered"


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
# native module and overwrite each other. That is handled by keeping them in
# different environments (see base_requirements), and in the 'remote' sandbox,
# which has only one, by install ordering (see
# sandbox_versions.GUARD_INVALIDATED_BY).
#
# ocpsvg is bounded for the same reason: it depends on the proxy directly and
# build123d's own bound on it is wide.
#
# The numba entry is a different problem that lands in the same file: a platform
# gap, the one sandbox_versions.NLOPT documents, one layer further down and with
# the opposite failure mode. 'cadquery' 2.8 depends on numba, numba depends on
# llvmlite, and the two dropped macOS x86_64 wheels in lockstep -- numba 0.62.1
# and llvmlite 0.45.1 are the last releases that publish one (cp310 through
# cp313), and from numba 0.63.0 / llvmlite 0.46.0 there are none at all.
#
# Unlike nlopt, both still publish an sdist. So pip does not run out of
# candidates and fall back to an older release; it takes the newest and tries to
# *build* it, and building llvmlite needs an LLVM the runner does not have:
# "CMake Error at CMakeLists.txt:21 (find_package): Could not find a package
# configuration file provided by 'LLVM'", which fails the whole
# "pip install cadquery==2.8.0" and leaves the sandbox with no CAD stack. A bare
# version range cannot fix that the way NLOPT's does -- the bound has to be one
# pip applies on Intel macOS and nowhere else, which is what the marker is for.
#
# Capping numba alone is enough: numba 0.62.1 declares 'llvmlite<0.46', so the
# llvmlite installed beside it is 0.45.1 by construction. Its other bound,
# 'numpy<2.4', still intersects sandbox_versions.NUMPY ('numpy>=2.2,<3').
#
# Every other platform is left entirely unconstrained, which is the point of the
# marker: the resolve on Linux, Windows and Apple silicon is unchanged.
#
# The residual gap NLOPT describes applies here too: Intel macOS wheels stop at
# cp313, so a 3.14 sandbox on that platform still finds nothing to install.
PIP_CONSTRAINTS = [
    "cadquery-ocp-proxy>=7.9,<8.0",
    "ocpsvg>=0.6,<0.7",
    'numba<=0.62.1; sys_platform == "darwin" and platform_machine == "x86_64"',
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


def package_requirements(project) -> list[str]:
    """What a package declares its Python sandbox needs.

    Shared by PythonRuntime.prepare_for_package() and by the cache key the
    factories build (see part_factory_python.PartFactoryPython), so the two
    cannot come to different conclusions about what a sandbox holds.

    A module-level function rather than a static method on the runtime:
    telemetry.instrument() rewrites every callable in a class body, and a
    'staticmethod' object is callable, so it would come back out as a plain
    function and turn into a bound method on the way through an instance.
    """
    # TODO(clairbee): expire the guard file after a certain time
    dependencies = []
    if "pythonRequirements" in project.config_obj:
        reqs = project.config_obj["pythonRequirements"]
        if isinstance(reqs, str):
            reqs = reqs.strip().split("\n")
        for req in reqs:
            # Skip blanks and comments, the way the requirements.txt branch
            # below does: a multiline 'pythonRequirements' can carry both, and
            # they are neither installable nor part of the environment.
            req = req.strip()
            if req and not req.startswith("#"):
                dependencies.append(req)
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
    return [dep for dep in dependencies if dep]


def shape_docker_image(config, project):
    """The image one shape's sandbox is built from.

    The shape's own declaration, then the package's. Same order as
    'pythonVersion' and 'pythonRequirements', and for the same reason: what a
    shape needs is nearer to it than what its package needs, and a package-wide
    image is the fallback rather than the answer. Reading only the package's
    meant a part naming an image was rendered without it -- in an environment
    that could be missing exactly the native library the part named it for.

    Module-level for the same reason 'shape_requirements' is.
    """
    return (config or {}).get("dockerImage") or getattr(project, "docker_image_declared", None)


def shape_requirements(config) -> list[str]:
    """What one shape declares its Python sandbox needs.

    Module-level for the same reason package_requirements() is.
    """
    if "pythonRequirements" not in config:
        return []
    reqs = config["pythonRequirements"]
    if isinstance(reqs, str):
        reqs = reqs.strip().split("\n")
    return [req.strip() for req in reqs if req and req.strip()]


def environment_requirements(project, config) -> list[str]:
    """Everything installed into the sandbox a shape renders in.

    The CAD stack PartCAD supplies comes first: every sandbox carries it, the
    base or a layer over it, and 'reconcile_requirement()' holds a package to
    those versions, so a bump moves every sandboxed shape - which is the point,
    since those versions are what produced it.

    The package's and the shape's own requirements are then reconciled the same
    way the installer reconciles them, so that a requirement PartCAD would
    override does not key as though it had been honored.
    """
    requirements = list(sandbox_versions.PINNED_REQUIREMENTS)
    requirements += package_requirements(project)
    requirements += shape_requirements(config)
    return [sandbox_versions.reconcile_requirement(requirement)[0] for requirement in requirements]


@telemetry.instrument()
def base_requirements(version: str) -> list:
    """What every Python sandbox has installed before anything runs in it, in order.

    One list, read by every sandbox, because two were how the ``remote`` sandbox
    came to install none of it: it collected each package's and each shape's own
    requirements and never this, so the first wrapper to deserialize a shape died
    on "No module named 'OCP'" -- in the remote sandbox, and in the ``docker``
    sandbox in ``upload`` mode, which is the same code.

    It is what a sandbox's own environment holds, and all it holds: build123d,
    the OCP build without VTK that build123d depends on, and what the wrappers
    read a request with. That is everything a wrapper imports except CadQuery,
    which needs the OCP build *with* VTK -- the two write the same native module,
    so they cannot share an environment -- and so runs in a layer over this one
    (see VENV_PREFIX). nlopt is here although only CadQuery uses it: with it,
    every CadQuery run adds the same two requirements to the base and shares one
    layer, rather than one layer for parts and another for the 3MF export.

    The 'remote' sandbox installs this into its one environment and CadQuery's
    OCP after it when asked; see sandbox_versions.GUARD_INVALIDATED_BY. zstd is
    not here; see 'ensure_zstd_onced_locked'.
    """
    return [
        sandbox_versions.OCP_TESSELLATE,
        sandbox_versions.NLOPT,
        sandbox_versions.NUMPY,
        sandbox_versions.TYPING_EXTENSIONS,
        sandbox_versions.OCPSVG,
        sandbox_versions.BUILD123D,
        sandbox_versions.OCP,
    ]


class PythonRuntime(runtime.Runtime):
    def __init__(self, ctx, sandbox, version=None):
        if version is None:
            version = "%d.%d" % (sys.version_info.major, sys.version_info.minor)
        super().__init__(ctx, "py-" + sandbox + "-" + version + "-" + SANDBOX_LAYOUT)
        self.sandbox = sandbox
        self.version = version
        self.is_mamba = False

        # Where the base keeps its packages, as its own interpreter reports
        # them: what every layer's LAYER_PTH names. Asked once per runtime.
        self.base_site_dirs = None

        # Whether once() has run to completion in this process. The sandbox
        # itself is provisioned once and for all, but every run_async(),
        # ensure_async() and prepare_for_*() used to re-enter once() to find
        # that out -- taking the runtime lock, and, under conda, spawning an
        # interpreter to ask the prefix its version -- several times for every
        # single file rendered.
        self.provisioned = False

        # Requirements already reported as superseded by the pinned CAD stack,
        # so the warning is emitted once per runtime instead of once per part.
        self.superseded_requirements = set()

        # The path to the Python executable
        self.exec_path = None
        # The name of the Python executable to search for in bin folders
        self.exec_name = "python" if os.name != "nt" else "python.exe"

        # Isolate this sandbox environment from the rest of the system.
        #
        # "-s" keeps the user's site-packages out; the rest of what isolation
        # takes now comes from the environment, which PartCAD sanitized at
        # startup (see python_env). This used to be "-I", which additionally
        # implied "-E" (ignore every PYTHON* variable) and "-P" -- but "-E"
        # cannot be selective, so it also made PartCAD unable to *set* a
        # PYTHON* variable for the sandbox, PYTHONHASHSEED above all. Dropping
        # the variables once, at startup, isolates just as well and leaves that
        # channel open; PYTHONSAFEPATH stands in for "-P".
        #
        # Except below 3.11, where PYTHONSAFEPATH does not exist and is ignored
        # in silence. There what "-P" stands for has to be had from "-I"
        # instead -- but only on the commands that need it, which is not every
        # command a sandbox runs:
        #
        # * Provisioning ("-m venv", "-m pip") inherits the directory PartCAD
        #   itself was started in, and for a "-m" command sys.path[0] is that
        #   directory. A "venv.py" or "pip.py" sitting in it is imported instead
        #   of the module meant, so provisioning keeps "-I" below 3.11.
        # * Everything else is a wrapper, run by path. For a script sys.path[0]
        #   is the *script's* directory -- PartCAD's own 'wrappers/', never a
        #   directory a user writes to -- so there is nothing there for "-P" to
        #   keep out, and "-I" adds no isolation that "-s" and the sanitized
        #   environment do not already provide.
        #
        # Keeping the two apart is what lets an old interpreter have both. "-I"
        # implies "-E", so a command carrying it ignores PYTHONHASHSEED and
        # hashes with a random seed; confined to provisioning that costs
        # nothing, as pip and venv have no output whose order anyone compares.
        # Carried by the wrapper runs as well -- as it was until this split --
        # it cost every sandbox below 3.11 its reproducibility, and bought
        # protection for a directory that was never on sys.path to begin with.
        try:
            has_safe_path = sandbox_versions.is_at_least(self.version, sandbox_versions.MIN_PYTHON_VERSION_SAFE_PATH)
        except ValueError:
            # A 'pythonVersion' the schema permits but neither this nor the
            # sandbox naming can read -- ">=3.12", which 'pc init' writes into
            # every new package (see Context.get_python_runtime). Unreadable
            # means "cannot be shown to have PYTHONSAFEPATH", so it isolates the
            # way an old interpreter does rather than trusting a variable that
            # may be ignored.
            has_safe_path = False
        self.python_flags = ["-sOOu"]
        self.python_provisioning_flags = ["-sOOu"] if has_safe_path else ["-sOOIu"]

        # TODO(clairbee): To improve portability, warn about uses of default encoding
        # self.python_flags += ["-X", "warn_default_encoding=1"]

        self.pip_flags = []
        # The newest release a requirement allows that has a wheel for this
        # machine, rather than the newest release. pip ranks a newer sdist above
        # an older wheel, so the day a project stops publishing wheels for a
        # platform, every sandbox there starts compiling it -- with no compiler,
        # or without the native library the build looks for -- and fails. That
        # is the numba gap in PIP_CONSTRAINTS, which PartCAD can bound because the
        # CAD stack is its own; a plugin's 'pythonRequirements' are not, and this
        # covers them. MuJoCo is the case in point: its last Intel macOS wheel is
        # 3.10.0, and 'mujoco>=3.2,<4' built 3.14.0 there and stopped on
        # "MUJOCO_PATH environment variable is not set".
        #
        # Only a preference: a requirement with no wheel at all for this machine
        # is still built from its sdist, which is what works where there is a
        # compiler.
        self.pip_install_flags = ["--prefer-binary"]
        if platform.system() == "Windows":
            self.pip_install_flags += ["--no-warn-script-location"]

        self.constraints_path = None

    def flags_for(self, cmd):
        """The interpreter flags a sandbox command line runs with.

        Below 3.11 provisioning is isolated with "-I" and everything else is
        not (see __init__ for why), and provisioning is exactly the set of
        commands spelled "-m venv" / "-m pip". Reading that off the command
        rather than off the caller keeps the two from drifting apart: a
        provisioning call site added later is isolated without anyone having to
        remember to ask for it, and a wrapper run cannot acquire "-I" -- and
        with it a random hash seed -- by accident.

        At 3.11 and above the two are the same list, since PYTHONSAFEPATH
        covers both.
        """
        return self.python_provisioning_flags if cmd and cmd[0] == "-m" else self.python_flags

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

    # ------------------------------------------------------------- layers --
    #
    # Each step comes in the two flavours the rest of this class does, and the
    # caller holds the layer's lock for writing. See VENV_PREFIX for what a
    # layer is.

    def provision_layer_onced_locked(self, session) -> None:
        """Build a session's layer if need be, link it to the base and install what it adds."""
        path = session["path"]
        created = not os.path.exists(path)
        if created:
            with pc_logging.Action("v-env", self.version, session["name"]):
                pc_logging.debug("Creating a layer: %s" % path)
                exitcode, _, stderr = self.run_onced_locked(["-m", "venv", "--upgrade-deps", path])
            layer_created(path, exitcode, stderr)
        if not os.path.exists(get_guard_path(path, LAYER_GUARD)):
            site_dirs = self.base_site_dirs
            if site_dirs is None:
                exitcode, stdout, stderr = self.run_onced_locked(list(BASE_SITE_DIRS_COMMAND))
                site_dirs = read_site_dirs(exitcode, stdout, stderr)
                self.base_site_dirs = site_dirs
            exitcode, _, stderr = self.run_onced_locked([*LINK_LAYER_COMMAND, *site_dirs], path=path)
            layer_linked(path, exitcode, stderr)
        for requirement in session["missing"]:
            self.ensure_onced_locked(requirement, path=path)
        if created:
            self.check_deps_onced_locked(path=path)

    async def provision_layer_async_onced_locked(self, session) -> None:
        """The asynchronous twin of provision_layer_onced_locked()."""
        path = session["path"]
        created = not os.path.exists(path)
        if created:
            with pc_logging.Action("v-env", self.version, session["name"]):
                pc_logging.debug("Creating a layer: %s" % path)
                exitcode, _, stderr = await self.run_async_onced_locked(["-m", "venv", "--upgrade-deps", path])
            layer_created(path, exitcode, stderr)
        if not os.path.exists(get_guard_path(path, LAYER_GUARD)):
            site_dirs = self.base_site_dirs
            if site_dirs is None:
                exitcode, stdout, stderr = await self.run_async_onced_locked(list(BASE_SITE_DIRS_COMMAND))
                site_dirs = read_site_dirs(exitcode, stdout, stderr)
                self.base_site_dirs = site_dirs
            exitcode, _, stderr = await self.run_async_onced_locked([*LINK_LAYER_COMMAND, *site_dirs], path=path)
            layer_linked(path, exitcode, stderr)
        for requirement in session["missing"]:
            await self.ensure_async_onced_locked(requirement, path=path)
        if created:
            await self.check_deps_async_onced_locked(path=path)

    def environment_path(self, session=None, path=None) -> str:
        """The environment a command with these arguments runs out of.

        The same three-way choice get_venv_python_path() makes, and it has to
        stay that way: this is what the environment lock is keyed on, so a
        command that locks one environment and runs in another is a command
        running unlocked.
        """
        if path is not None:
            return path
        if session is not None and session["dirty"]:
            return session["path"]
        return self.path

    def environment_lock(self, session=None, path=None):
        """The lock over the environment a command runs out of.

        A layer's lock is named by the hash in its directory name, and the
        sandbox's own environment's is "default".

        What has changed is which of them a given command takes -- the
        environment it runs in, rather than the session it was asked for, which
        for every package without requirements of its own was a lock over an
        environment nobody used.
        """
        environment_path = self.environment_path(session, path)
        name = os.path.basename(os.path.normpath(environment_path))
        if name.startswith(VENV_PREFIX):
            name = name[len(VENV_PREFIX) :]
        elif os.path.normpath(environment_path) == os.path.normpath(self.path):
            name = "default"
        else:
            name = hashlib.sha256(environment_path.encode()).hexdigest()[:16]
        lock_path = os.path.join(self.ctx.user_config.internal_state_dir, f".{self.sandbox_dir}.{name}.lock")
        return sandbox_lock.get(lock_path)

    @contextlib.contextmanager
    def sync_lock(self, session=None, path=None, write=False):
        """Hold the environment a command runs out of.

        'write' for anything that installs into the environment or creates it,
        which excludes everyone else; without it the environment is only being
        read, and any number of wrappers may read it at once. That is the whole
        of the difference between this and the single per-runtime mutex it
        replaces, which held every wrapper of every environment in one queue.
        """
        with self.environment_lock(session, path).acquire(write=write):
            yield

    @contextlib.asynccontextmanager
    async def async_lock(self, session=None, path=None, write=False):
        """The asynchronous twin of sync_lock()."""
        async with self.environment_lock(session, path).acquire_async(write=write):
            yield

    @contextlib.contextmanager
    def sync_lock_install(self, session=None):
        """Lock the runtime and the venv environment for installation of packages"""
        yield

    @contextlib.asynccontextmanager
    async def async_lock_install(self, session=None):
        """Lock the runtime and the venv environment for installation of packages"""
        yield

    def ensure_zstd_onced_locked(self):
        """Install what the sandbox needs to read a compressed BREP payload.

        Every wrapper needs this one, including those that install nothing else:
        the request the host writes to their stdin carries zstd-compressed BREP
        (see wrappers/ocp_serialize.py).

        The install guard makes this a single stat() once it has run.
        """
        zstd = sandbox_versions.zstd_requirement(self.version)
        if zstd:
            self.ensure_onced_locked(zstd)

    async def ensure_zstd_onced_locked_async(self):
        """Asynchronous counterpart of ensure_zstd_onced_locked()."""
        zstd = sandbox_versions.zstd_requirement(self.version)
        if zstd:
            await self.ensure_async_onced_locked(zstd)

    def once(self):
        if self.provisioned:
            return
        with self.sync_lock(write=True):
            with self.sync_lock_install():
                self.ensure_zstd_onced_locked()
                # Asked of the guards every time rather than only of a sandbox
                # directory that did not exist yet: each is a stat() once it is
                # installed, and a sandbox whose provisioning was interrupted
                # is completed by the next process to use it -- rather than
                # left short of part of its base, which every layer over it
                # would then install a copy of.
                for requirement in base_requirements(self.version):
                    self.ensure_onced_locked(requirement)
                self.initialized = True
        self.provisioned = True

    async def once_async(self):
        if self.provisioned:
            return
        async with self.async_lock(write=True):
            async with self.async_lock_install():
                await self.ensure_zstd_onced_locked_async()
                # See the note beside the same lines in 'once'.
                for requirement in base_requirements(self.version):
                    await self.ensure_async_onced_locked(requirement)
                self.initialized = True
        self.provisioned = True

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
        # Hold the lock of the environment the run reads -- its layer, or the
        # sandbox's own -- across both provisioning and execution, so that no
        # interpreter starts in a layer while something is being installed into
        # it: a package half written is a package that fails to import, with an
        # error that names neither the install nor the run.
        #
        # It is taken for writing only while that is still ahead: a run whose
        # layer has been provisioned, and every run out of the sandbox's own
        # environment, is only reading what is installed, and any number of
        # those may read it at once. See run_async_onced() for
        # the async twin.
        with self.sync_lock(session, path=path, write=self.session_needs_install(session)):
            if self.session_needs_install(session):
                # We already hold the layer's lock, so take the install lock
                # inside it; the resulting order (layer lock, then the conda
                # global lock) matches once()/ensure and cannot deadlock.
                with self.sync_lock_install():
                    self.provision_layer_onced_locked(session)

            python_path = self.get_venv_python_path(session, path)
            cmd = [python_path, *self.flags_for(cmd), *cmd]
            pc_logging.debug("Running: %s", cmd)
            # pc_logging.debug("stdin: %s", stdin)
            with (
                sandbox_lock.process_slots.slot(),
                telemetry.start_as_current_span("PythonRuntime.run_onced.*{subprocess.Popen}") as span,
            ):
                # Strip user home directory from the path, if any
                sanitized_cmd = copy.copy(cmd)
                sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
                span.set_attribute("cmd", " ".join(sanitized_cmd))
                argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, self._subprocess_env())
                # Bytes rather than text, like 'run_async_onced' beside it: the
                # output is decoded by 'process_output.decode', which replaces a
                # byte it cannot read instead of raising on it. Asking Popen for
                # 'encoding="utf-8"' would decode strictly, before that ever ran
                # -- and it also made 'communicate' reject the encoded stdin two
                # lines below, so this path raised on the way in as well as out.
                # Written before the process starts: a request that cannot be written
                # then fails with no child left waiting on its standard input.
                data = runtime.stdin_bytes(stdin)
                with runtime.output_capture(self.OUTPUT_TO_FILES) as capture:
                    p = subprocess.Popen(
                        argv,
                        stdin=subprocess.PIPE,
                        stdout=capture.stdout,
                        stderr=capture.stderr,
                        shell=False,
                        env=spawn_env,
                        # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                        cwd=spawn_cwd,
                    )
                    # Over when the interpreter is, not when the last process
                    # holding its output lets go (see 'runtime.communicate').
                    stdout, stderr = capture.collect(*runtime.communicate_sync(p, data))

            # A wrapper's answer stays the frame of bytes it is; see 'process_output.answer'.
            stdout = stdout_of(stdout)
            stderr = decode_output(stderr)
            returncode, stderr = self._ended(p.returncode, stderr)

            if stdout:
                pc_logging.debug("Output of %s: %s", cmd, loggable(stdout))
            if stderr:
                if returncode == 0:
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
            exitcode = 0 if returncode in [3221226356, 3221225477] else returncode

            if exitcode != 0:
                # A negative exit code means the interpreter was killed rather
                # than that it failed, and the caller reports whatever comes
                # back from here -- left to itself, the raw number, which names
                # neither the signal nor the fact that there was one. So say it
                # here, once, for every caller.
                #
                # Saying nothing at all on the way out is the case worth
                # guessing about: it is what a native crash looks like, and a
                # fault in the CAD kernel and two incompatible OCP builds are
                # the two things that produce it.
                crash = describe_termination(
                    cmd,
                    returncode,
                    where=path if path else self.path,
                    silent=not stdout and not stderr,
                )
                if crash:
                    stderr = crash if not stderr else stderr.rstrip() + "\n" + crash

            return exitcode, stdout, stderr

    def run_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        if self.session_needs_install(session):
            self.provision_layer_onced_locked(session)

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.flags_for(cmd), *cmd]
        pc_logging.debug("Running: %s", cmd)
        # pc_logging.debug("stdin: %s", stdin)
        exitcode, stdout, stderr = super().run(cmd, stdin=stdin, cwd=cwd)
        return exitcode, stdout, stderr

    async def run_async(self, cmd, stdin="", cwd=None, session=None, timeout=None):
        await self.once_async()
        return await self.run_async_onced(cmd, stdin=stdin, cwd=cwd, session=session, timeout=timeout)

    async def run_async_onced(self, cmd, stdin="", cwd=None, session=None, path=None, timeout=None):
        # 'timeout' bounds the interpreter run alone, deliberately: everything
        # above it here -- waiting for the environment lock, creating the v-env,
        # installing this session's dependencies -- is provisioning that is
        # shared with every other caller of this sandbox and that legitimately
        # takes minutes on a cold machine. A bound that covered it would fire on
        # a slow install rather than on the script it is meant to bound.
        # Hold the lock of the environment the run reads -- its layer, or the
        # sandbox's own -- across both provisioning and execution, so that no
        # interpreter starts in a layer while something is being installed into
        # it: a package half written is a package that fails to import, with an
        # error that names neither the install nor the run.
        #
        # It is taken for writing only while that is still ahead: a run whose
        # layer has been provisioned, and every run out of the sandbox's own
        # environment, is only reading what is installed, and any number of
        # those may read it at once.
        async with self.async_lock(session, path=path, write=self.session_needs_install(session)):
            if self.session_needs_install(session):
                # See the note beside the same lines in 'run_onced'.
                async with self.async_lock_install():
                    await self.provision_layer_async_onced_locked(session)

            python_path = self.get_venv_python_path(session, path)
            cmd = [python_path, *self.flags_for(cmd), *cmd]
            pc_logging.debug("Running: %s", cmd)
            # pc_logging.debug("stdin: %s", stdin)
            async with sandbox_lock.process_slots.slot_async():
                with telemetry.start_as_current_span("PythonRuntime.run_async_onced.*{subprocess.Popen}") as span:
                    # Strip user home directory from the path, if any
                    sanitized_cmd = copy.copy(cmd)
                    sanitized_cmd[0] = os.path.join("...", os.path.basename(sanitized_cmd[0]))
                    span.set_attribute("cmd", " ".join(sanitized_cmd))
                    argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, self._subprocess_env())
                    # See the notes beside the same lines in 'run_onced'.
                    data = runtime.stdin_bytes(stdin)
                    with runtime.output_capture(self.OUTPUT_TO_FILES) as capture:
                        p = await asyncio.create_subprocess_exec(
                            *argv,
                            stdin=subprocess.PIPE,
                            stdout=capture.stdout,
                            stderr=capture.stderr,
                            shell=False,
                            env=spawn_env,
                            # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                            cwd=spawn_cwd,
                            # A bounded run is a process group of its own, so that
                            # the bound stops all of it; see 'bounded_spawn_options'.
                            **runtime.bounded_spawn_options(timeout),
                        )
                        stdout, stderr = capture.collect(*await runtime.communicate(p, data, timeout))

            # A wrapper's answer stays the frame of bytes it is; see 'process_output.answer'.
            stdout = stdout_of(stdout)
            stderr = decode_output(stderr)
            returncode, stderr = await self._ended_async(p.returncode, stderr)

            if stdout:
                pc_logging.debug("Output of %s: %s", cmd, loggable(stdout))
            if stderr:
                if returncode == 0:
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
            exitcode = 0 if returncode in [3221226356, 3221225477] else returncode

            if exitcode != 0:
                # A negative exit code means the interpreter was killed rather
                # than that it failed, and the caller reports whatever comes
                # back from here -- left to itself, the raw number, which names
                # neither the signal nor the fact that there was one. So say it
                # here, once, for every caller.
                #
                # Saying nothing at all on the way out is the case worth
                # guessing about: it is what a native crash looks like, and a
                # fault in the CAD kernel and two incompatible OCP builds are
                # the two things that produce it.
                crash = describe_termination(
                    cmd,
                    returncode,
                    where=path if path else self.path,
                    silent=not stdout and not stderr,
                )
                if crash:
                    stderr = crash if not stderr else stderr.rstrip() + "\n" + crash

            return exitcode, stdout, stderr

    async def run_async_onced_locked(self, cmd, stdin="", cwd=None, session=None, path=None):
        if self.session_needs_install(session):
            await self.provision_layer_async_onced_locked(session)

        python_path = self.get_venv_python_path(session, path)
        cmd = [python_path, *self.flags_for(cmd), *cmd]
        pc_logging.debug("Running: %s", cmd)
        exitcode, stdout, stderr = await super().run_async(cmd, stdin=stdin, cwd=cwd)
        return exitcode, stdout, stderr

    def ensure(self, python_package, session=None, path=None, force=False):
        self.once()
        self.ensure_onced(python_package, session=session, path=path, force=force)

    def reconcile_requirement(self, python_package):
        """Hold the CAD stack in a sandbox to the versions PartCAD pins.

        A part that asks for its own version of cadquery-ocp, build123d,
        cadquery, ocp-tessellate, ocpsvg or nlopt would otherwise get it in a
        layer of its own, over a sandbox holding the pinned one -- a second CAD
        stack on disk, and half of each on sys.path, which dies inside the
        wrapper with an ImportError or AttributeError that names neither the
        offending package nor the version that caused it. Before sandboxes were
        layered it downgraded the stack under every part sharing the package's
        v-env instead (see sandbox_versions.PINNED_REQUIREMENTS).

        Substituting the pinned version keeps the sandbox coherent, and the
        warning - once per runtime, not once per part - says what was overridden
        so a package that genuinely needs another version is not left guessing.
        """
        python_package, superseded = sandbox_versions.reconcile_requirement(python_package)
        if superseded is not None and superseded not in self.superseded_requirements:
            self.superseded_requirements.add(superseded)
            pc_logging.warning(
                "Installing '%s' instead of '%s': PartCAD pins the CAD stack across a sandbox, "
                "and mixing versions of it breaks the other parts that share the same environment."
                % (python_package, superseded)
            )
        return python_package

    def ensure_onced(self, python_package, session=None, path=None, force=False):
        python_package = self.reconcile_requirement(python_package)
        if path is None:
            path = self.path

        force = force or needs_reassert(path, python_package)
        if session:
            self.ask_of_session(session, python_package, path)
        elif not self.installed_onced(python_package, path, force):
            self.warn_base_install(python_package, path)
            with self.sync_lock(path=path, write=True):
                with self.sync_lock_install():
                    self.install_onced_locked(python_package, path, force)

    def installed_onced(self, python_package, path, force=False) -> bool:
        """Whether 'path' already holds this package.

        The install guard is the record, and reading it is the whole of the
        fast path: only a requirement that is genuinely missing makes a caller
        take the environment's write lock and so wait behind every wrapper
        running out of it. Every requirement of every file rendered used to
        take that lock to find out there was nothing to do.
        """
        if force:
            return False
        return os.path.exists(get_guard_path(path, python_package))

    def install_label(self, python_package, path):
        item = get_local_partcad_pkg(python_package) if python_package == "partcad" else python_package
        return item if path is None else item + " in " + path

    def pip_install_command(self, python_package, force):
        return [
            "-m",
            "pip",
            *self.pip_flags,
            "install",
            *self.pip_install_flags,
            *self.get_constraints_flags(),
            *(FORCE_REINSTALL_FLAGS if force else []),
            python_package,
        ]

    def record_install(self, python_package, path):
        """Note that a package is in 'path', and what that install clobbered.

        Only ever called after an install has actually run. The dependent
        guards say "these packages have just had their files overwritten", so
        dropping them when nothing was installed asks for the next render to
        re-install a package that was never touched -- which, since build123d
        invalidates cadquery-ocp and every image file type installs both, is a
        forced re-install of the whole of OCP per rendered file.
        """
        pathlib.Path(get_guard_path(path, python_package)).touch()
        clear_reassert(path, python_package)
        invalidate_dependent_guards(path, python_package)

    def install_onced_locked(self, python_package, path, force=False):
        """Install one package. The environment's write lock is already held."""
        if self.installed_onced(python_package, path, force):
            return
        with pc_logging.Action("PipInst", self.version, self.install_label(python_package, path)):
            exitcode, _, stderr = self.run_onced_locked(self.pip_install_command(python_package, force), path=path)
        self.record_install_unless_killed(python_package, path, exitcode, stderr)

    async def install_async_onced_locked(self, python_package, path, force=False):
        """The asynchronous twin of install_onced_locked()."""
        if self.installed_onced(python_package, path, force):
            return
        with pc_logging.Action("PipInst", self.version, self.install_label(python_package, path)):
            exitcode, _, stderr = await self.run_async_onced_locked(
                self.pip_install_command(python_package, force), path=path
            )
        self.record_install_unless_killed(python_package, path, exitcode, stderr)

    def record_install_unless_killed(self, python_package, path, exitcode, stderr):
        """Record an install that ran -- unless pip was killed while running it, which is raised instead.

        A pip the out-of-memory killer took in the middle of an install has left
        the environment half written, and recording the install anyway told
        every run after it that the package was there: they failed on an import
        that named nothing about the death, and nothing ever installed it again.
        So the death is the failure of whatever needed the package, said with
        the signal (see 'process_crash'), and nothing is recorded -- the next
        run that needs the package installs it afresh.

        A pip that ran to the end and exited with an error is recorded as it
        always has been; whether it should be is a question of its own.
        """
        if killed_by_signal(exitcode):
            raise RuntimeError(
                "Installing '%s' into %s did not finish: %s"
                % (python_package, path, (stderr or "").strip() or describe_exit_code(exitcode))
            )
        self.record_install(python_package, path)

    def ensure_onced_locked(self, python_package, session=None, path=None, force=False):
        python_package = self.reconcile_requirement(python_package)
        if path is None:
            path = self.path

        force = force or needs_reassert(path, python_package)
        if session:
            self.ask_of_session(session, python_package, path)
        else:
            self.install_onced_locked(python_package, path, force)

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        await self.once_async()
        await self.ensure_async_onced(python_package, session=session, path=path, force=force)

    async def ensure_async_onced(self, python_package, session=None, path=None, force=False):
        python_package = self.reconcile_requirement(python_package)
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time
        force = force or needs_reassert(path, python_package)
        if session:
            self.ask_of_session(session, python_package, path)
        elif not self.installed_onced(python_package, path, force):
            self.warn_base_install(python_package, path)
            async with self.async_lock(path=path, write=True):
                async with self.async_lock_install():
                    await self.install_async_onced_locked(python_package, path, force)

    async def ensure_async_onced_locked(self, python_package, session=None, path=None, force=False):
        python_package = self.reconcile_requirement(python_package)
        if path is None:
            path = self.path

        # TODO(clairbee): expire the guard file after a certain time

        force = force or needs_reassert(path, python_package)
        if session:
            self.ask_of_session(session, python_package, path)
        else:
            await self.install_async_onced_locked(python_package, path, force)

    async def prepare_for_package(self, project, session=None):
        await self.once_async()

        for dep in package_requirements(project):
            # Use local partcad package instead of the deployed one (specifically intended to be used during testing)
            if dep == "partcad":
                dep = get_local_partcad_pkg(dep)
            await self.ensure_async_onced(dep, session=session)

    async def prepare_for_shape(self, config, session=None):
        await self.once_async()

        # Install dependencies of this part
        for req in shape_requirements(config):
            await self.ensure_async_onced(req, session)

    def get_venv_python_path(self, session=None, path=None):
        use_venv = False

        if path is None:
            if session is None or not session["dirty"]:
                # Use the full interpreter path if known
                if self.exec_path is not None:
                    return self.exec_path
                # If the full path is not known, use the interpreter name
                path = self.path
            else:
                path = session["path"]
                use_venv = True
        elif str(os.path.basename(path)).startswith(VENV_PREFIX):
            use_venv = True
        elif self.exec_path is not None and os.path.normpath(path) == os.path.normpath(self.path):
            # The runtime's own directory, for a sandbox whose interpreter does
            # not live inside it.
            #
            # 'none' is that sandbox: it runs whatever Python the host has, and
            # its directory holds guard files and a constraints file rather than
            # an environment. Every install defaults to that directory
            # ('ensure_*' fills 'path' in with 'self.path'), so without this the
            # interpreter that installs a package is '<sandbox>/bin/python' -- a
            # file that never existed -- while the interpreter that then runs
            # the wrapper is 'exec_path'. Nothing was installed where anything
            # was looked for, and on a clean machine the install could not even
            # start.
            return self.exec_path
        else:
            # A conda prefix: its interpreter really is inside it.
            use_venv = False

        if os.name == "nt":
            if use_venv:
                python_path = os.path.join(path, "Scripts", self.exec_name)
            else:
                python_path = os.path.join(path, self.exec_name)
        else:
            python_path = os.path.join(path, "bin", self.exec_name)

        return python_path

    def session_needs_install(self, session=None) -> bool:
        """Whether running this session still has to install anything.

        Which is the same question as whether the run needs its layer for
        writing, so the two must be asked the same way: a run that installs
        while holding the layer for reading is a run installing behind the back
        of every wrapper reading it.

        Asked of the layer itself -- its guards, which an install writes only
        once it has finished -- rather than of what this session has seen
        installed. Every part has a session of its own, and a session that had
        to find out for itself would take its layer for writing on its first
        run, and so wait for every run of the layer in progress to end; the
        parts sharing a layer would start one after another.
        """
        if not session or not session["dirty"]:
            return False
        return not self.layer_ready(session)

    def layer_ready(self, session) -> bool:
        """Whether a session's layer has been linked to the base and holds what the session adds."""
        path = session["path"]
        if not os.path.exists(get_guard_path(path, LAYER_GUARD)):
            return False
        return all(self.installed_onced(requirement, path) for requirement in session["missing"])

    def get_session(self, name: str):
        """What a run needs beyond the base, and so which layer it runs in, if any.

        A session collects what its run asks for ('ensure*(session=...)'). What
        the base already holds costs nothing; anything else makes the session
        'dirty' and is added to 'missing', and the session's layer is the one
        named after 'missing' (see 'place_session'). 'name' is what the session
        is for, and is only ever shown.
        """
        return {
            "name": name,
            "hash": None,
            "path": None,
            "dirty": False,
            # Everything asked for, in the order asked.
            "deps": [],
            # What of 'deps' the base does not hold: what the layer adds.
            "missing": [],
        }

    def place_session(self, session) -> None:
        """Name the layer a session runs in after what it adds to the base.

        The name is a digest of those requirements as a set, so every run that
        adds the same ones -- every CadQuery part, whatever its package, and the
        3MF export -- shares one layer, and a package whose parts ask for
        nothing the base lacks has none.
        """
        digest = hashlib.sha256("\n".join(sorted(set(session["missing"]))).encode()).hexdigest()[:16]
        session["hash"] = digest
        session["path"] = os.path.join(self.path, VENV_PREFIX + digest)

    def ask_of_session(self, session, python_package, path=None) -> None:
        """Note that a session's run needs a package, and whether the base has it."""
        session["deps"].append(python_package)
        if self.installed_onced(python_package, self.path if path is None else path):
            return
        if python_package == "partcad":
            # The local package during tests (see get_local_partcad_pkg), which
            # is what the layer's guard is then named after.
            python_package = get_local_partcad_pkg(python_package)
        if python_package not in session["missing"]:
            session["missing"].append(python_package)
            self.place_session(session)
        session["dirty"] = True

    def warn_base_install(self, python_package, path) -> None:
        """Say so when something installs into the base after it was provisioned.

        Nothing PartCAD runs should: what the base lacks belongs in a layer, and
        an install into the base rewrites packages under every wrapper reading
        it. A caller that asks for a package without a session is one that
        meant a package the base has.
        """
        if os.path.normpath(path) != os.path.normpath(self.path):
            return
        pc_logging.warning(
            "Installing '%s' into the %s sandbox's own environment after it was provisioned; "
            "anything the base does not hold belongs in a layer" % (python_package, self.sandbox)
        )
