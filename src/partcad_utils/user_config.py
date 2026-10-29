#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import importlib._bootstrap
import importlib._bootstrap_external
import importlib.machinery
import importlib.util
import math
import os
import shutil
from pathlib import Path

import vyper

from . import conda as pc_conda
from . import logging as pc_logging
from .booleans import to_bool
from .utils import is_editable_install

# IMPORTANT:
# We need to maintain setting default values in both the CLI and the user_config, because of:
# 1) CLI needs default values to show them to the user
# 2) CLI pushes the default values to user_config unconditionally (if no user values are set)
# 3) user_config is used outside of CLI, where CLI default values are not available


class BaseConfig(dict):
    def __init__(self, v: vyper.Vyper, path: str):
        self._v = v
        self._path = path

    @property
    def _config(self):
        return self._v.get(self._path) or {}

    def __getitem__(self, key):
        return self._config.get(key)

    def __setitem__(self, key, value):
        config = self._config
        config[key] = value
        self._v.set(self._path, config)

    def __delitem__(self, key):
        config = self._config
        if key in config:
            del config[key]
            self._v.set(self._path, config)

    def __iter__(self):
        return iter(self._config)

    def __contains__(self, key):
        # The 'dict' this subclasses is never filled -- everything is in the
        # Vyper behind it -- so without this every 'in' answered False.
        return key in self._config

    def __len__(self):
        return len(self._config)

    def __getattr__(self, key):
        return self._config.get(key)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._config})"

    def to_dict(self):
        return self._config.copy()


class GitConfig(BaseConfig):
    def __init__(self, v):
        super().__init__(v, "git.config")


class GitAuthConfig(BaseConfig):
    """Credentials for private Git remotes, keyed by host (or "default")."""

    def __init__(self, v):
        super().__init__(v, "git.auth")


class PIIConfig(BaseConfig):
    def __init__(self, v):
        super().__init__(v, "user")
        self.__populate_addresses()

    def __populate_addresses(self):
        data = self._config
        child_fields = ["shippingAddress", "billingAddress"]
        parent_fields = [field for field in data.keys() if field not in child_fields]

        for address_type in child_fields:
            if address_type in data:
                for field in parent_fields:
                    if field not in data[address_type]:
                        data[address_type][field] = data.get(field)
            else:
                data[address_type] = {field: data.get(field) for field in parent_fields}

        self._v.set(self._path, data)


class ParametersConfig(BaseConfig):
    def __init__(self, v):
        super().__init__(v, "parameters")


# TODO(clairbee): make TelemetryConfig a subclass of BaseConfig
class TelemetryConfig(dict):
    def __init__(self, v: vyper.Vyper):
        self.v = v
        self.v.bind_env("telemetry.type", "PC_TELEMETRY_TYPE")
        self.v.bind_env("telemetry.detail", "PC_TELEMETRY_DETAIL")
        self.v.bind_env("telemetry.env", "PC_TELEMETRY_ENV")
        self.v.bind_env("telemetry.performance", "PC_TELEMETRY_PERFORMANCE")
        self.v.bind_env("telemetry.failures", "PC_TELEMETRY_FAILURES")
        self.v.bind_env("telemetry.debug", "PC_TELEMETRY_DEBUG")
        self.v.bind_env("telemetry.sentryDsn", "PC_TELEMETRY_SENTRY_DSN")
        self.v.bind_env("telemetry.sentryShutdownTimeout", "PC_TELEMETRY_SENTRY_SHUTDOWN_TIMEOUT")
        self.v.bind_env("telemetry.sentryAttachStacktrace", "PC_TELEMETRY_SENTRY_ATTACH_STACKTRACE")
        self.v.bind_env("telemetry.sentryTracesSampleRate", "PC_TELEMETRY_SENTRY_TRACES_SAMPLE_RATE")
        self.v.register_alias("telemetry.environment", "telemetry.env")

    @property
    def type(self):
        try:
            if self.v.is_set("telemetry.type"):
                return self.v.get_string("telemetry.type")
        except:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.type" in self.v._override:
                return self.v._override["telemetry.type"]
            telemetry = self.v._config.get("telemetry", {})
            if "type" in telemetry:
                return telemetry["type"]

        return "sentry"

    @property
    def detail(self):
        """How deep the tracing goes: 'actions' (the default) or 'methods'.

        'actions' is one span per operation PartCAD names - the processes and
        the actions its own log lines are built from ('Action: InitWrapper',
        'Process: ListAssemblies'). That is the shape of what a command does.

        'methods' adds a span for every instrumented method underneath them.
        It is what a trace needs to answer "where inside this did the time go",
        and it is expensive in a way that is easy to miss: creating one part
        goes through a dozen instrumented methods, so a package of eight
        thousand of them is a quarter of a million spans for a listing. It is
        available, and it is not the default.
        """
        try:
            if self.v.is_set("telemetry.detail"):
                return self.v.get_string("telemetry.detail")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.detail" in self.v._override:
                return self.v._override["telemetry.detail"]
            telemetry = self.v._config.get("telemetry", {})
            if "detail" in telemetry:
                return telemetry["detail"]

        return "actions"

    @property
    def env(self):
        try:
            if self.v.is_set("telemetry.env"):
                return self.v.get_string("telemetry.env")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.env" in self.v._override:
                return self.v._override["telemetry.env"]
            telemetry = self.v._config.get("telemetry", {})
            if "env" in telemetry:
                return telemetry["env"]

        if is_editable_install(pc_logging):
            return "dev"
        else:
            return "prod"

    @property
    def performance(self):
        try:
            if self.v.is_set("telemetry.performance"):
                return self.v.get_bool("telemetry.performance")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.performance" in self.v._override:
                return to_bool(self.v._override["telemetry.performance"])
            telemetry = self.v._config.get("telemetry", {})
            if "performance" in telemetry:
                return to_bool(telemetry["performance"])

        return True

    @property
    def failures(self):
        try:
            if self.v.is_set("telemetry.failures"):
                return self.v.get_bool("telemetry.failures")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.failures" in self.v._override:
                return to_bool(self.v._override["telemetry.failures"])
            telemetry = self.v._config.get("telemetry", {})
            if "failures" in telemetry:
                return to_bool(telemetry["failures"])

        return True

    @property
    def debug(self):
        try:
            if self.v.is_set("telemetry.debug"):
                return self.v.get_bool("telemetry.debug")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.debug" in self.v._override:
                return to_bool(self.v._override["telemetry.debug"])
            telemetry = self.v._config.get("telemetry", {})
            if "debug" in telemetry:
                return to_bool(telemetry["debug"])

        return False

    @property
    def sentry_dsn(self):
        try:
            if self.v.is_set("telemetry.sentryDsn"):
                return self.v.get_string("telemetry.sentryDsn")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.sentryDsn" in self.v._override:
                return self.v._override["telemetry.sentryDsn"]
            telemetry = self.v._config.get("telemetry", {})
            if "sentryDsn" in telemetry:
                return telemetry["sentryDsn"]

        # TODO(clairbee): create a load balancer for Sentry
        # return "https://sentry.partcad.org"
        return "https://3a80dc66ff544e5000cb4c50751f0eca@o4508651588485120.ingest.us.sentry.io/4508651601526784"

    @property
    def sentry_shutdown_timeout(self):
        try:
            if self.v.is_set("telemetry.sentryShutdownTimeout"):
                return self.v.get_float("telemetry.sentryShutdownTimeout")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.sentryShutdownTimeout" in self.v._override:
                return self.v._override["telemetry.sentryShutdownTimeout"]
            telemetry = self.v._config.get("telemetry", {})
            if "sentryShutdownTimeout" in telemetry:
                return telemetry["sentryShutdownTimeout"]

        return 3.0

    @property
    def sentry_attach_stacktrace(self):
        try:
            if self.v.is_set("telemetry.sentryAttachStacktrace"):
                return self.v.get_bool("telemetry.sentryAttachStacktrace")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.sentryAttachStacktrace" in self.v._override:
                return to_bool(self.v._override["telemetry.sentryAttachStacktrace"])
            telemetry = self.v._config.get("telemetry", {})
            if "sentryAttachStacktrace" in telemetry:
                return to_bool(telemetry["sentryAttachStacktrace"])

        return False

    @property
    def sentry_traces_sample_rate(self):
        try:
            if self.v.is_set("telemetry.sentryTracesSampleRate"):
                return self.v.get_float("telemetry.sentryTracesSampleRate")
        except Exception:  # pragma: no cover
            # Workaround for https://github.com/alexferl/vyper/pull/71
            if "telemetry.sentryTracesSampleRate" in self.v._override:
                return self.v._override["telemetry.sentryTracesSampleRate"]
            telemetry = self.v._config.get("telemetry", {})
            if "sentryTracesSampleRate" in telemetry:
                return telemetry["sentryTracesSampleRate"]

        return 1.0

    def __repr__(self):
        properties = []
        for name, val in vars(TelemetryConfig).items():
            if isinstance(val, property):
                properties.append((name, val.__get__(self, TelemetryConfig)))
        return str({k: v for k, v in properties})


def _positive_seconds(value):
    """'value' as a positive, finite number of seconds, or None.

    A setting read from the environment arrives as text, so text that is a
    number is one; a boolean is not, although Python would count it as 1.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


# The options a user configuration resolves to, by their configuration-file
# names. This is what travels when one process hands its configuration to
# another; a new option belongs here, or the daemon will keep resolving it from
# its own environment instead of the caller's.
OPTION_KEYS = (
    "threadsMax",
    "cacheMem",
    "cacheFiles",
    "cacheFilesMaxEntrySize",
    "cacheFilesMinEntrySize",
    "cacheMemoryMaxEntrySize",
    "cacheMemoryDoubleCacheMaxEntrySize",
    "cacheRemote",
    "cacheRemoteServer",
    "cacheRemoteNamespace",
    "cacheRemoteExpiration",
    "cacheRemoteMaxEntrySize",
    "cacheRemoteMinEntrySize",
    "cacheS3",
    "cacheS3Bucket",
    "cacheS3Prefix",
    "cacheS3Region",
    "cacheS3EndpointUrl",
    "cacheS3MaxEntrySize",
    "cacheS3MinEntrySize",
    "cacheDependenciesIgnore",
    "cacheBypass",
    "pythonSandbox",
    "pythonSandboxZygote",
    "remoteSandbox",
    "remoteSandboxToken",
    "ignoreBundledOpenscad",
    "internalStateDir",
    "logLevel",
    "forceUpdate",
    "develIndex",
    "offline",
    "git.clone.timeout",
    "git.clone.retry.max",
    "git.clone.retry.patience",
    "plugin.query.timeout",
    "simulation.timeout",
    "simulation.videoResolution",
    "useDocker",
    "useDockerPython",
    "useDockerKicad",
    "useDockerRemote",
    "caeFeaImplementation",
    "caeDynamicImplementation",
    "caeThermalImplementation",
    "caeCfdImplementation",
    "camImplementation",
    "tags",
)

# The nested sections, by the path each configuration view reads. 'git.auth'
# carries credentials for private dependencies; it travels because the daemon is
# meant to ignore its own configuration, and a caller whose configuration is the
# only one holding those credentials would otherwise fail to clone.
#
# 'telemetry' is deliberately absent, on two counts. It is a property of a
# process rather than of a package: it is initialized once at import
# (telemetry.init) long before any context exists, and nothing in context
# creation or dependency resolution reads it, so a copy of it would be inert --
# and a daemon reporting under a caller's DSN and environment would be wrong
# even if it were not. It is also the one key that cannot be read safely:
# reading a parent that has environment-bound children makes vyper merge each of
# those children into the mapping the config file gave, and raise KeyError when
# the mapping does not already carry that child. 'PC_TELEMETRY_ENV=test' over a
# config file without a 'telemetry.env' is enough, which is what CI runs under.
# The same happens when reading a 'telemetry.*' leaf that is not set, because
# the lookup descends to that parent. It is the vyper bug that the try/except in
# TelemetryConfig above is already written around.
#
# The sections below are safe for the same reason inverted: none is the parent
# of an environment-bound key. 'git.clone.timeout' and the 'git.clone.retry.*'
# pair hang off 'git', which is why 'git' is never read whole -- only
# 'git.config' and 'git.auth' are.
SECTION_PATHS = (
    "git.config",
    "git.auth",
    "parameters",
    "user",
)


# Which implementation each CAE analysis is run by when nothing says otherwise.
# A package path and a file type in it, exactly as a user would write one, and
# both live in the public PartCAD index. They are not built into 'partcad': a
# solver is a large third-party program, and which one to run is the user's
# decision (see the 'caeFeaImplementation' option below).
#
# Each is the implementation whose answer to `examples/feature_cae` was measured
# against the closed form: CalculiX for a static stress analysis; Elmer for the
# two it is alone in covering with FEA as well, dynamic and thermal; OpenFOAM for
# a flow, which is the one CalculiX's own CFD solver diverges on.
DEFAULT_CAE_IMPLEMENTATIONS = {
    "fea": "//pub/feature/cae/calculix:fea",
    "dynamic": "//pub/feature/cae/elmer:dynamic",
    "thermal": "//pub/feature/cae/elmer:thermal",
    "cfd": "//pub/feature/cae/openfoam:cfd",
}

# Which implementation produces a route when nothing says otherwise. Unlike the
# two above this one *is* built into 'partcad': a route is arithmetic on the
# object's own outline rather than somebody else's program, so PartCAD ships it
# (see 'partcad.output.BUILTIN_PACKAGES'). The option exists all the same,
# because which post-processor a shop's machine reads is that shop's answer and
# not PartCAD's.
DEFAULT_CAM_IMPLEMENTATION = "//builtin/cam:gcode"


# The least 'threadsMax' may be, wherever it comes from: the configuration file,
# PC_THREADS_MAX, '--threads-max', or a configuration a client hands the daemon.
# A lower value is raised to this, with a warning, and the same floor holds for
# what PartCAD picks when nothing says (see 'default_threads_max').
#
# Four is a floor on how much PartCAD does at once, kept for performance. What
# 'threadsMax' sizes strictly is how many sandbox processes run at the same time
# ('partcad.sandbox_lock'), and with them the constrained thread pool they are
# waited for from; a recursive render starts every object of a package at once
# and spends most of its time waiting for those processes, so it is the number
# of them that decides how long it takes. Four is the least PartCAD runs with.
#
# It is no longer what keeps a render going. It was introduced when
# 'threadsMax: 2' stopped 'pc render -r' for good: an object built from another
# one -- an alias, an enrich, an extrusion of a sketch -- held a thread of the
# constrained pool while it waited for a second one to build its source on, and
# as many of those at once as the pool had threads held them all. Raising the
# floor only made that less likely: pools of four and seven stopped the same
# way, with four and seven such objects at once. Work started on a slot of the
# pools now runs on that slot, and a slot waiting for a lock held by something
# that waits for the pool gives the slot back, so a pool of any size -- one
# thread included -- builds nested objects to the end (see
# 'partcad.sync_threads'). A lower value would no longer stop anything, and is
# raised all the same: the floor is about how much PartCAD does at once, not
# about whether it finishes.
THREADS_MAX_MINIMUM = 4


def cpu_cores() -> int:
    """How many CPU cores this machine has, as PartCAD counts them.

    'os.cpu_count()', which is what PartCAD's sizing has always counted: the
    cores the machine has, not the ones this process may run on -- it knows
    nothing of an affinity mask or a container's CPU quota. One function, so
    that the sizing, the warning below and 'pc healthcheck' cannot count two
    different ways.
    """
    return os.cpu_count() or 1


def few_cores_warning(cores: int) -> str:
    """What a machine with fewer cores than the minimum is told.

    The sizing below notes it once per process, and 'pc healthcheck' warns of
    it when asked (partcad.healthcheck.cpu_cores); one sentence, so that a
    search for the one finds the other.
    """
    return "PartCAD needs at least %d CPU cores for optimal performance, and found %d" % (THREADS_MAX_MINIMUM, cores)


def default_threads_max() -> int:
    """What 'threadsMax' comes to when nothing sets it: one per core, at least the minimum.

    A machine with fewer cores than that is told so, once per process: it gets
    the minimum regardless, the least PartCAD runs with (see
    'THREADS_MAX_MINIMUM'), and that is more processes than it has cores to run
    them.

    Told as information, not as a warning. Nothing about the command it is
    said during can change it, and as a warning it was in the output of the
    first command every new daemon served: a check that a command warns of
    nothing -- 'enrich.feature' has one -- failed on a three-core machine and
    nowhere else. 'pc healthcheck' is where it is a warning, being where the
    machine is what is asked about.
    """
    cores = cpu_cores()
    if cores < THREADS_MAX_MINIMUM:
        pc_logging.info_once(("cpu_cores", cores), few_cores_warning(cores))
    return max(THREADS_MAX_MINIMUM, cores)


def threads_max_at_least_minimum(value, origin: str = None):
    """'value' as a 'threadsMax': a whole number no lower than the minimum, or None.

    None stays None: nothing was said, and what PartCAD picks then is
    'default_threads_max()'. A lower number is raised to the minimum, and the
    user is told, once per process for each value -- the client resolves its
    configuration more than once per command, and the daemon is handed one with
    every request. 'origin' says where the value came from, when that is known.

    A value that is not a whole number is not one PartCAD can run with, and is
    ignored with a warning rather than allowed to stop the process: this runs
    while 'partcad_utils' is imported, where a 'ValueError' is a traceback before
    any command has started.
    """
    if value is None:
        return None
    where = " (from %s)" % origin if origin else ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        pc_logging.warning_once(
            ("threadsMax", repr(value)),
            "threadsMax %r%s is not a whole number, and is ignored" % (value, where),
        )
        return None
    if number < THREADS_MAX_MINIMUM:
        pc_logging.warning_once(
            ("threadsMax", number),
            "threadsMax %d%s is below the minimum of %d; using %d instead"
            % (number, where, THREADS_MAX_MINIMUM, THREADS_MAX_MINIMUM),
        )
        return THREADS_MAX_MINIMUM
    return number


class UserConfig(vyper.Vyper):
    # The sandbox before anything has been read. Both are replaced during
    # '__init__'; they exist as class attributes so that the property below
    # answers on a half-built object, which 'vyper.Vyper.__init__' can reach
    # through '__setattr__' before ours has run.
    _python_sandbox = None
    _python_sandbox_declared = False
    # The same, for 'threads_max'.
    _threads_max = None

    @property
    def threads_max(self):
        """How much of the machine PartCAD may use: 'threadsMax', or None for "pick".

        A property, so that no way of setting it gets past the floor:
        '--threads-max' arrives by assignment after the configuration has been
        read, and so does any caller that sets the attribute.
        """
        return self._threads_max

    @threads_max.setter
    def threads_max(self, value):
        self._apply_threads_max(value)

    def _apply_threads_max(self, value, origin: str = None):
        self._threads_max = threads_max_at_least_minimum(value, origin)
        # Into the settings as well as the attribute, so that the two cannot
        # disagree about what stands. What travels to the daemon is read off the
        # attribute ('to_dict'), which is the half that matters: '--threads-max'
        # used to set the attribute alone, and so never reached a daemon at all.
        if self._threads_max is not None:
            self.set("threadsMax", self._threads_max)

    @staticmethod
    def _threads_max_origin(settings) -> str:
        """Where the 'threadsMax' being read came from, in the order vyper ranks them."""
        if settings and settings.get("threadsMax") is not None:
            return "the caller's configuration"
        if os.environ.get("PC_THREADS_MAX"):
            return "PC_THREADS_MAX"
        return UserConfig.get_config_path()

    @property
    def python_sandbox(self):
        """Which sandbox to build Python environments in.

        A property so that setting it counts as a decision. '--python-sandbox'
        arrives this way -- the CLI assigns the attribute after the
        configuration has been read -- and a decision, however it arrives, is
        obeyed rather than second-guessed by the container-runtime check in
        'Context.get_python_runtime'.
        """
        return self._python_sandbox

    @python_sandbox.setter
    def python_sandbox(self, value):
        self._python_sandbox = value
        self._python_sandbox_declared = True

    @property
    def python_sandbox_declared(self) -> bool:
        """Whether the sandbox above was asked for rather than picked."""
        return self._python_sandbox_declared

    def get_bool(self, key):
        """Read a boolean option, believing "0", "no" and "off".

        vyper's own implementation treats every string but "false" as true,
        because it never converts a value -- it hands back what it was given and
        falls through to ``bool()``. That is a fine default for a library that
        does not know where its values came from, but PartCAD does: every one of
        these keys is bound to a ``PC_*`` environment variable, and an
        environment variable can only carry a string. Under vyper's reading,
        ``PC_FORCE_UPDATE=0`` turned the flag *on*.

        The conversion is therefore PartCAD's to make, and making it here makes
        it once: every boolean option, including the ones ``TelemetryConfig``
        reads through this same object, gets the same answer. It is also the
        answer ``pc`` already gave, since click converts the same variable with
        its own BOOL type -- so ``pc`` and the daemon it launches stop
        disagreeing about what the environment said.
        """
        return to_bool(self.get(key))

    @staticmethod
    def get_config_dir():
        home = os.environ.get("HOME", Path.home())
        return os.path.join(home, ".partcad")

    @staticmethod
    def get_config_path():
        """The configuration file itself: the first of the layers '__init__' resolves.

        Next to the directory above rather than derived from it at each call
        site, for the reason 'get_generated_id_path' below gives: a path spelled
        twice is a path that can be read from one place and written to another.
        A report of what the configuration resolved to has to name this file,
        and naming a different one would make the report a lie exactly when
        somebody is using it to find out why an option did not take.
        """
        return os.path.join(UserConfig.get_config_dir(), "config.yaml")

    @staticmethod
    def get_cache_dir():
        return os.path.join(Path.home(), ".cache", "partcad")

    @staticmethod
    def get_generated_id_path():
        """Where the telemetry id lives: one identifier per user, generated once.

        Next to the configuration file, not in `internalStateDir`. That
        directory holds caches, sandboxes and clones, and can be pointed
        somewhere else per installation or per run -- the snap package points it
        at the snap's own per-user directory -- and an identity that moved with
        it would make one user look like several.

        Defined in one place because it used to be defined in two: the id was
        written here and read back from `internalStateDir` by `pc system
        telemetry info` and `pc system telemetry clear`, which agreed only for as
        long as nothing set PC_INTERNAL_STATE_DIR.
        """
        return os.path.join(UserConfig.get_config_dir(), ".generated_id")

    def to_dict(self) -> dict:
        """This configuration as plain data, ready to hand to another process.

        A PartCAD client resolves its own configuration -- a config file, the
        ``PC_*`` environment, and the command line on top of each other -- and
        then asks the daemon to do the work. The daemon has a configuration of
        its own, resolved from its own environment when it was launched and warm
        ever since, which is not the one the command was invoked with. Sending
        this alongside the request is what lets the daemon build the context
        from the caller's configuration instead of its own.

        Only the resolved options are copied, keyed by their configuration-file
        names, plus the nested sections. A value that resolved to nothing is
        left out rather than sent as null, so that reconstructing it falls back
        to the same default rather than overriding the option with an empty one.
        """
        data = {}
        for key in OPTION_KEYS:
            value = self.get(key)
            if value is not None:
                data[key] = value
        for path in SECTION_PATHS:
            value = self.get(path)
            if value:
                data[path] = value
        # 'threadsMax' as it stands rather than as the layers last spelled it:
        # raised to the minimum, a value that is not a number dropped, and
        # whatever the command line assigned. Sent that way, the daemon has
        # nothing to raise and nothing to warn about -- the user has been told
        # once already, by the process that read the setting.
        data.pop("threadsMax", None)
        if self._threads_max is not None:
            data["threadsMax"] = self._threads_max
        # Whether the sandbox was somebody's decision, which the value cannot
        # say: every process resolves one, so the receiving end would read the
        # startup default as a statement. See '__init__'.
        data["pythonSandboxDeclared"] = self._python_sandbox_declared
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        """Rebuild a configuration from what :meth:`to_dict` produced."""
        return cls(settings=data)

    def __init__(self, settings: dict = None):
        """Resolve the configuration: the file, the `PC_*` environment, `settings`.

        Each option below is read once and kept as an attribute, so that a
        caller asks the object rather than the layers underneath it. `settings`
        is what `from_dict` passes when a daemon is rebuilding a *caller's*
        configuration rather than resolving its own.
        """
        super().__init__()
        self.set_config_type("yaml")

        cfg_dir = UserConfig.get_config_dir()
        os.makedirs(cfg_dir, exist_ok=True)
        config_path = UserConfig.get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    self.read_config(f)
            except Exception as e:
                pc_logging.error("ERROR: Failed to parse %s: %s" % (config_path, str(e)))

        # A configuration handed over by another process, applied before
        # anything below reads a value back. These land as vyper overrides,
        # which outrank the file just read and the environment bound further
        # down, so every option resolves to what the caller resolved it to and
        # this process's own environment is ignored -- which is the point when
        # the caller is a CLI and this process is the daemon serving it.
        if settings:
            for key, value in settings.items():
                self.set(key, value)

        # If the filesystem cache is enabled, then (by default):
        # - objects of 1 byte bytes are cached both in memory and on the filesystem (to cache test results)
        # - objects from 2 bytes to 100 bytes are cached in memory only (avoid filesystem polution and overhead),
        # - objects from 100 bytes to 1MB are cached both in the filesystem and in memory (where most cache hits are expected),
        # - objects from 1MB bytes to 50MB are cached in the filesystem only (optimize RAM usage).
        # - objects from 50MB to 100MB are cached in memory only (avoid quick filesystem quota depletion).
        # - object above 100MB are not cached and recomputed on each access (avoid RAM depletion).
        # If the filesystem cache is disabled then (by default):
        # - objects from 1 to 100MB are cached in memory only.
        # - object above 100MB are not cached and recomputed on each access.
        #
        # The cache is a hierarchy of tiers, and each one has its own switch and
        # its own size window, because what is worth keeping in RAM is not what
        # is worth a file, and neither is what is worth a network round trip:
        #
        #   cacheMem     this process's memory. Nearest, and lost on exit.
        #   cacheFiles   a directory under the internal state directory. Local.
        #   cacheRemote  a memcached server shared by a team or a CI fleet.
        #   cacheS3      an object store, which outlives all of the above.
        #                Needs the 'aws' extra.
        #
        # A read walks them in that order and stops at the first hit; a write
        # offers the entry to every tier whose window accepts it. The two remote
        # tiers are off by default: they need an address that only a deployment
        # can supply.
        self.set_default("cacheMem", True)
        self.set_default("cacheMemoryMaxEntrySize", 100 * 1024 * 1024)
        self.set_default("cacheMemoryDoubleCacheMaxEntrySize", 1 * 1024 * 1024)
        self.set_default("cacheFiles", True)
        # 50MB rather than 10MB: an assembly's tree is one entry, each distinct
        # payload in it once (see cache_shape._TREE_MAGIC), and the LEGO F1's
        # distinct geometry alone is 10.9MB - over 10MB it was put together
        # again from its sub-assemblies on every run.
        self.set_default("cacheFilesMaxEntrySize", 50 * 1024 * 1024)
        self.set_default("cacheFilesMinEntrySize", 100)
        self.set_default("cacheRemote", False)
        self.set_default("cacheRemoteServer", "")
        self.set_default("cacheRemoteNamespace", "partcad")
        self.set_default("cacheRemoteExpiration", 7 * 24 * 60 * 60)
        # memcached's own default item size limit. Sending more only earns a
        # rejection, so a server raised above it has to say so here.
        self.set_default("cacheRemoteMaxEntrySize", 1024 * 1024)
        self.set_default("cacheRemoteMinEntrySize", 100)
        self.set_default("cacheS3", False)
        self.set_default("cacheS3Bucket", "")
        self.set_default("cacheS3Prefix", "partcad/")
        self.set_default("cacheS3Region", "")
        self.set_default("cacheS3EndpointUrl", "")
        # S3 takes far larger objects than this, but an entry that big is
        # slower to fetch than to rebuild, which is not a cache hit worth having.
        self.set_default("cacheS3MaxEntrySize", 100 * 1024 * 1024)
        self.set_default("cacheS3MinEntrySize", 100)
        self.set_default("cacheDependenciesIgnore", False)
        self.set_default("cacheBypass", False)

        # Whether the *user* said which sandbox to use, as opposed to PartCAD
        # picking one below. Captured before the default is set, because
        # 'is_set()' cannot tell a default from a decision afterwards -- and the
        # difference matters: an unstated preference is upgraded to the 'docker'
        # sandbox where a container runtime answers (see
        # 'Context.get_python_runtime'), and a stated one is obeyed.
        #
        # The environment is checked directly rather than waited for: the
        # binding below happens after this point, and '--python-sandbox' arrives
        # later still, through the property this sets up.
        # A configuration handed over by another process says so itself. It
        # cannot be worked out from the value: 'to_dict' copies the startup
        # default along with everything else, and applying that copy is a vyper
        # override, which 'is_set' cannot tell from a decision. So every daemon
        # saw a declared 'conda' or 'venv', obeyed it, and never upgraded to the
        # 'docker' sandbox that the same command run in-process would choose.
        if settings is not None and "pythonSandboxDeclared" in settings:
            self._python_sandbox_declared = bool(settings["pythonSandboxDeclared"])
        else:
            self._python_sandbox_declared = bool(self.is_set("pythonSandbox")) or bool(
                os.environ.get("PC_PYTHON_SANDBOX")
            )

        # conda first, because it is the only sandbox that can provision an
        # *interpreter*: a package asking for a Python the host does not have
        # gets it. Failing that, a virtual environment of PartCAD's own, which
        # is still a sandbox -- it installs where it runs, and nothing it
        # installs reaches the interpreter the user works with.
        #
        # Not 'none'. That one has no environment at all: it renders with the
        # host's interpreter and installs the CAD stack into it, which is a
        # surprising thing to do to somebody's Python and impossible on a host
        # whose Python is not writable. It stays available for a host that wants
        # exactly that, and is chosen rather than fallen back to.
        #
        # `pc_conda.find_executable()` rather than `shutil.which("conda")`: it is
        # the same question the sandbox itself asks later
        # (`CondaPythonRuntime.find_conda_executable`), and asking it differently
        # here is how the two came to disagree. It answers for a host `mamba`
        # with no `conda` beside it -- which the sandbox has always preferred and
        # this default used to miss -- and for the conda a standalone bundle
        # carries. That last one is why the bundle is not left to the `venv`
        # fallback: a venv is built *from* an interpreter, and the machine a
        # bundle exists for is the machine with no Python to build one from.
        if pc_conda.find_executable() is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("pythonSandbox", "conda")
        else:
            self.set_default("pythonSandbox", "venv")

        # Unlike Python, whose sandbox has to be provisioned because PartCAD's
        # own interpreter is the wrong one to render in, a host Node.js is
        # simply used when there is one: it costs nothing, and the dependency
        # tree - which is what actually has to be isolated - is provisioned
        # either way. conda is the fallback, so a host without Node.js still
        # works if conda can supply one.
        if shutil.which("node") is not None:
            self.set_default("javascriptSandbox", "none")
        elif pc_conda.find_executable() is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("javascriptSandbox", "conda")
        else:
            self.set_default("javascriptSandbox", "none")

        self.set_default("internalStateDir", UserConfig.get_config_dir())
        self.set_default("forceUpdate", False)
        # PartCAD running from its sources (an editable install: 'pip install
        # -e', 'poetry install') is PartCAD being developed, so it gets the
        # index being developed. See 'develIndex' below.
        self.set_default("develIndex", is_editable_install(pc_logging))

        # option: git.clone.timeout
        # description: how long a single git network operation (clone, fetch,
        #              pull) may take before it is aborted, in seconds. Without
        #              a bound, an unreachable or stalled remote hangs partcad
        #              indefinitely; the clone retry logic does not help because
        #              a hang never raises GitCommandError.
        # values: <int>
        # default: 180
        self.set_default("git.clone.timeout", 180)

        # option: git.clone.retry.max
        # description: how many more times a clone or refresh of a git
        #              dependency is attempted after a transient network
        #              failure -- the timeout above, a refused or reset
        #              connection, a 5xx (see 'git_error_patterns' in
        #              partcad.project_factory_git). An answer about the
        #              repository itself, such as a 404, a missing ref or a
        #              refused credential, is reported at once whatever this
        #              says. There was no default, and an unset key reads as 0,
        #              so a single dropped connection to GitHub failed the whole
        #              command even though the retry loop had recognized it as
        #              transient.
        #
        #              Two, because each attempt can take up to the timeout
        #              above: a remote that has really gone away now costs three
        #              of those rather than one before the error is reported.
        # values: <int>
        # default: 2
        self.set_default("git.clone.retry.max", 2)

        # option: git.clone.retry.patience
        # description: how long to wait before each of those retries, in seconds
        # values: <float>
        # default: 5.0
        self.set_default("git.clone.retry.patience", 5.0)

        # option: plugin.query.timeout
        # description: how long one query to a package's plugin script may take
        #              before PartCAD gives up on it, in seconds. A plugin
        #              script is third-party code that PartCAD waits for; a
        #              repository plugin that enumerates a category by fetching
        #              every part in it over the network can run for hours, and
        #              without a bound "pc list -r" simply stops producing
        #              output and never returns. Three minutes, the same as
        #              "git.clone.timeout" above and for the same reason: it is
        #              what a whole network operation is allowed, and one
        #              key/value query is far less than that.
        # values: <int>
        # default: 180
        self.set_default("plugin.query.timeout", 180)

        self.set_default("useDocker", True)
        self.set_default("useDockerPython", False)
        self.set_default("useDockerKicad", True)
        self.set_default("useDockerRemote", False)
        self.set_default("tags", "")

        self.set_env_prefix("pc")

        # option: threadsMax
        # description: how much of the machine PartCAD may use. Sizes the thread
        #              pools (not a strict limit) and, strictly, how many sandbox
        #              interpreters run at once (partcad.sandbox_lock). A daemon
        #              sizes the latter for each request from the configuration
        #              the request carries, so PC_THREADS_MAX and '--threads-max'
        #              take effect on a daemon that was started without them.
        # values: >=4 (THREADS_MAX_MINIMUM); a lower value is raised to 4 with a
        #         warning, whether it comes from this file, PC_THREADS_MAX,
        #         '--threads-max' or a client's configuration
        # default: max(7, <cpu threads count - 1>) threads,
        #          max(4, <cpu threads count>) sandbox processes
        self.bind_env("threadsMax", "PC_THREADS_MAX")
        if self.is_set("threadsMax"):
            self._apply_threads_max(self.get("threadsMax"), self._threads_max_origin(settings))
        else:
            self._threads_max = None

        # option: cacheFiles
        # description: enable caching of intermediate results to the filesystem
        # values: [True | False]
        # default: True
        self.bind_env("cacheFiles", "PC_CACHE_FILES")
        self.cache = self.get_bool("cacheFiles")

        # option: cacheFilesMaxEntrySize
        # description: the maximum size of a single file cache entry in bytes
        # values: >0
        # default: 50*1024*1024 (50MB)
        self.bind_env("cacheFilesMaxEntrySize", "PC_CACHE_FILES_MAX_ENTRY_SIZE")
        self.cache_max_entry_size = self.get_int("cacheFilesMaxEntrySize")

        # option: cacheFilesMinEntrySize
        # description: the minimum size of a single file cache entry (except test results) in bytes
        # values: >=0
        # default: 100
        self.bind_env("cacheFilesMinEntrySize", "PC_CACHE_FILES_MIN_ENTRY_SIZE")
        self.cache_min_entry_size = self.get_int("cacheFilesMinEntrySize")

        # option: cacheMemoryMaxEntrySize
        # description: the maximum size of a single memory cache entry in bytes
        # values: >=0, 0 means no limit
        # default: 100*1024*1024 (100MB)
        self.bind_env("cacheMemoryMaxEntrySize", "PC_CACHE_MEMORY_MAX_ENTRY_SIZE")
        self.cache_memory_max_entry_size = self.get_int("cacheMemoryMaxEntrySize")

        # option: cacheMemoryDoubleCacheMaxEntrySize
        # description: the maximum size of a single memory cache entry in bytes
        # values: >=0, 0 means no limit
        # default: 1*1024*1024 (1MB)
        self.bind_env("cacheMemoryDoubleCacheMaxEntrySize", "PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE")
        self.cache_memory_double_cache_max_entry_size = self.get_int("cacheMemoryDoubleCacheMaxEntrySize")

        # option: cacheMem
        # description: enable caching of intermediate results in this process's memory
        # values: [True | False]
        # default: True
        self.bind_env("cacheMem", "PC_CACHE_MEM")
        self.cache_memory = self.get_bool("cacheMem")

        # option: cacheRemote
        # description: enable the shared remote cache, reached over the memcached
        #              protocol.
        # values: [True | False]
        # default: False
        self.bind_env("cacheRemote", "PC_CACHE_REMOTE")
        self.cache_remote = self.get_bool("cacheRemote")

        # option: cacheRemoteServer
        # description: the memcached server backing the remote cache, "host" or "host:port"
        # values: <string>
        # default: "" (port 11211 when the port is left out)
        self.bind_env("cacheRemoteServer", "PC_CACHE_REMOTE_SERVER")
        self.cache_remote_server = self.get_string("cacheRemoteServer")

        # option: cacheRemoteNamespace
        # description: prefix for every key this installation stores, so that
        #              several projects can share one memcached server
        # values: <string>
        # default: partcad
        self.bind_env("cacheRemoteNamespace", "PC_CACHE_REMOTE_NAMESPACE")
        self.cache_remote_namespace = self.get_string("cacheRemoteNamespace")

        # option: cacheRemoteExpiration
        # description: how long a remote cache entry lives, in seconds
        # values: >=0, 0 means no expiration
        # default: 604800 (7 days)
        self.bind_env("cacheRemoteExpiration", "PC_CACHE_REMOTE_EXPIRATION")
        self.cache_remote_expiration = self.get_int("cacheRemoteExpiration")

        # option: cacheRemoteMaxEntrySize
        # description: the maximum size of a single remote cache entry in bytes
        # values: >=0, 0 means no limit
        # default: 1*1024*1024 (1MB, memcached's own default)
        self.bind_env("cacheRemoteMaxEntrySize", "PC_CACHE_REMOTE_MAX_ENTRY_SIZE")
        self.cache_remote_max_entry_size = self.get_int("cacheRemoteMaxEntrySize")

        # option: cacheRemoteMinEntrySize
        # description: the minimum size of a single remote cache entry (except test results) in bytes
        # values: >=0
        # default: 100
        self.bind_env("cacheRemoteMinEntrySize", "PC_CACHE_REMOTE_MIN_ENTRY_SIZE")
        self.cache_remote_min_entry_size = self.get_int("cacheRemoteMinEntrySize")

        # option: cacheS3
        # description: enable the object store cache. Requires the 'aws' extra:
        #              pip install 'partcad[aws]'
        # values: [True | False]
        # default: False
        self.bind_env("cacheS3", "PC_CACHE_S3")
        self.cache_s3 = self.get_bool("cacheS3")

        # option: cacheS3Bucket
        # description: the bucket holding the object store cache
        # values: <string>
        # default: ""
        self.bind_env("cacheS3Bucket", "PC_CACHE_S3_BUCKET")
        self.cache_s3_bucket = self.get_string("cacheS3Bucket")

        # option: cacheS3Prefix
        # description: the key prefix within the bucket, so that one bucket can
        #              hold more than this cache
        # values: <string>
        # default: partcad/
        self.bind_env("cacheS3Prefix", "PC_CACHE_S3_PREFIX")
        self.cache_s3_prefix = self.get_string("cacheS3Prefix")

        # option: cacheS3Region
        # description: the AWS region of the bucket
        # values: <string>
        # default: "" (leave it to the standard AWS resolution chain)
        self.bind_env("cacheS3Region", "PC_CACHE_S3_REGION")
        self.cache_s3_region = self.get_string("cacheS3Region")

        # option: cacheS3EndpointUrl
        # description: an S3 endpoint other than AWS's own - a MinIO or Ceph
        #              deployment, or a test server
        # values: <string>
        # default: "" (AWS)
        self.bind_env("cacheS3EndpointUrl", "PC_CACHE_S3_ENDPOINT_URL")
        self.cache_s3_endpoint_url = self.get_string("cacheS3EndpointUrl")

        # option: cacheS3MaxEntrySize
        # description: the maximum size of a single object store cache entry in bytes
        # values: >=0, 0 means no limit
        # default: 100*1024*1024 (100MB)
        self.bind_env("cacheS3MaxEntrySize", "PC_CACHE_S3_MAX_ENTRY_SIZE")
        self.cache_s3_max_entry_size = self.get_int("cacheS3MaxEntrySize")

        # option: cacheS3MinEntrySize
        # description: the minimum size of a single object store cache entry (except test results) in bytes
        # values: >=0
        # default: 100
        self.bind_env("cacheS3MinEntrySize", "PC_CACHE_S3_MIN_ENTRY_SIZE")
        self.cache_s3_min_entry_size = self.get_int("cacheS3MinEntrySize")

        # option: cacheDependenciesIgnore
        # description: ignore broken dependencies and cache at your own risk
        # values: [True | False]
        # default: False
        self.bind_env("cacheDependenciesIgnore", "PC_CACHE_DEPENDENCIES_IGNORE")
        self.cache_dependencies_ignore = self.get_bool("cacheDependenciesIgnore")

        # option: cacheBypass
        # description: neither read from nor write to any cache tier (files,
        #              remote, S3) for this run: everything is built afresh and
        #              nothing built is kept. What '--cache-bypass' sets.
        # values: [True | False]
        # default: False
        self.bind_env("cacheBypass", "PC_CACHE_BYPASS")
        self.cache_bypass = self.get_bool("cacheBypass")

        # option: pythonSandbox
        # description: sandboxing environment for invoking python scripts
        # values: [docker | none | venv | pypy | conda | remote]
        # default: the best this machine can provide -- 'docker' where a
        #          container runtime answers, else conda where the host has it,
        #          else venv. Only the last two are decided here: asking whether
        #          a container runtime answers means talking to a daemon, and a
        #          command that never builds a sandbox should not pay for that.
        #          'Context.get_python_runtime' asks, the first time a sandbox is
        #          actually needed, and only when nothing was declared.
        self.bind_env("pythonSandbox", "PC_PYTHON_SANDBOX")
        self._python_sandbox = self.get_string("pythonSandbox")

        # option: pythonSandboxZygote
        # description: start each Python wrapper by forking an interpreter that
        #              has already imported the CAD stack -- one per sandbox
        #              environment, started on first use and retired whenever
        #              anything is installed into it -- instead of starting and
        #              importing a fresh one per call (partcad.sandbox_zygote).
        #              Only the sandboxes whose interpreter runs on this machine
        #              (venv, conda, none), and only on Linux: macOS and Windows
        #              always start a fresh interpreter. Turn it off to have
        #              Linux do the same.
        # values: [True | False]
        # default: True
        self.set_default("pythonSandboxZygote", True)
        self.bind_env("pythonSandboxZygote", "PC_PYTHON_SANDBOX_ZYGOTE")
        self.python_sandbox_zygote = self.get_bool("pythonSandboxZygote")

        # option: remoteSandbox
        # description: where 'partcad-service-remote-docker' is listening, as
        #              host:port. Only the 'remote' sandbox reads it, and that
        #              sandbox cannot work without it -- there is no default,
        #              because guessing at a service that runs commands is not
        #              a thing to do on somebody's behalf.
        # values: <host>:<port>
        # default: none
        self.bind_env("remoteSandbox", "PC_REMOTE_SANDBOX")
        self.remote_sandbox = self.get_string("remoteSandbox") if self.is_set("remoteSandbox") else None

        # option: remoteSandboxToken
        # description: the shared secret 'partcad-service-remote-docker' was
        #              started with, sent as a bearer token on every request.
        #              Needed only where that service listens on an address
        #              other than loopback -- it refuses to start on one
        #              without a token, because a service that runs commands
        #              and asks nothing of its callers is a remote shell for
        #              whoever can reach the port.
        # values: <string>
        # default: none
        self.bind_env("remoteSandboxToken", "PC_REMOTE_SANDBOX_TOKEN")
        self.remote_sandbox_token = self.get_string("remoteSandboxToken") if self.is_set("remoteSandboxToken") else None

        # option: javascriptSandbox
        # description: sandboxing environment for invoking JavaScript scripts
        # values: [none | conda]
        # default: none if the host has Node.js, else conda
        self.bind_env("javascriptSandbox", "PC_JAVASCRIPT_SANDBOX")
        self.javascript_sandbox = self.get_string("javascriptSandbox")

        # option: ignoreBundledOpenscad
        # description: ignore the OpenSCAD that the standalone bundle carries and
        #              use the one installed on the host instead. Only the
        #              standalone (PyInstaller) build carries an OpenSCAD; the
        #              wheels never do, so this has no effect there.
        # values: [True | False]
        # default: False
        # Bound to IGNORE_BUNDLED_OPENSCAD (without the PC_ prefix the other
        # options use) because it is a property of the bundle rather than of a
        # PartCAD run, so a user is likely to set it once in their environment.
        self.set_default("ignoreBundledOpenscad", False)
        self.bind_env("ignoreBundledOpenscad", "IGNORE_BUNDLED_OPENSCAD")
        self.ignore_bundled_openscad = self.get_bool("ignoreBundledOpenscad")

        # option: internalStateDir
        # description: folder to store all temporary files
        # values: <path>
        # default: '.partcad' folder in the home directory
        self.bind_env("internalStateDir", "PC_INTERNAL_STATE_DIR")
        self.internal_state_dir = self.get_string("internalStateDir")

        # option: logLevel
        # description: verbosity of the daemon's persistent rotating log file,
        #              independent of what any connected client requests
        # values: [debug | info | warning | error | critical]
        # default: debug (full detail)
        self.set_default("logLevel", "debug")
        self.bind_env("logLevel", "PC_LOG_LEVEL")
        self.log_level = self.get_string("logLevel")

        # option: forceUpdate
        # description: the "force auto-update": fetch every git dependency
        #              again each time a package is loaded, and use one that
        #              has 'track:' at the newest commit of that branch rather
        #              than at its 'revision:'. Off, a dependency is used as it
        #              was first downloaded until 'pc update' moves its pin.
        # values: [True | False]
        # default: False
        self.bind_env("forceUpdate", "PC_FORCE_UPDATE")
        self.force_update = self.get_bool("forceUpdate")

        # option: develIndex
        # description: take the public PartCAD index ("//pub") from its 'devel'
        #              branch instead of the released state on 'main'. The index
        #              lives in its own repository, so its version is not pinned
        #              by anything in the package that imports it; this is how a
        #              change staged there is exercised before it is released.
        #              Applies to every dependency whose URL names that
        #              repository, wherever in the dependency tree it appears,
        #              and leaves every other dependency alone.
        #              On by default where PartCAD runs from its sources, so
        #              that a feature under development is built against the
        #              packages being written for it before either is released.
        # values: [True | False]
        # default: True when PartCAD runs from its sources (an editable
        #          install), False otherwise
        self.bind_env("develIndex", "PC_DEVEL_INDEX")
        self.devel_index = self.get_bool("develIndex")

        # option: git.clone.timeout
        # description: seconds a single git network operation may take
        # values: <int>
        # default: 180
        self.bind_env("git.clone.timeout", "PC_GIT_CLONE_TIMEOUT")
        self.git_clone_timeout = self.get_int("git.clone.timeout")
        if not self.git_clone_timeout or self.git_clone_timeout <= 0:
            # An unset or nonsensical value must not turn the bound back off
            self.git_clone_timeout = 180

        # option: plugin.query.timeout
        # description: seconds one query to a plugin script may take
        # values: <int>
        # default: 180
        self.bind_env("plugin.query.timeout", "PC_PLUGIN_QUERY_TIMEOUT")
        self.plugin_query_timeout = self.get_int("plugin.query.timeout")
        if not self.plugin_query_timeout or self.plugin_query_timeout <= 0:
            # An unset or nonsensical value must not turn the bound back off
            self.plugin_query_timeout = 180

        # option: simulation.timeout
        # description: how long one simulation run may take on this machine,
        #              in wall-clock seconds, over whatever the simulation and
        #              its plugin declare. Unset, a run is given the 'timeout'
        #              its 'simulate:' passes in 'params', else its plugin's,
        #              else the larger of five minutes and ten times the
        #              simulated 'duration' (see 'partcad.simulation.run_budget').
        #              It is the one knob for somebody who cannot edit the
        #              package: a slow machine, or a CI job that would rather
        #              fail fast. It can lengthen and shorten a run alike, and
        #              it cannot turn the bound off: zero, a negative number or
        #              anything that is not one is no setting at all.
        # values: <float>
        # default: unset
        self.bind_env("simulation.timeout", "PC_SIMULATION_TIMEOUT")
        self.simulation_timeout = _positive_seconds(self.get("simulation.timeout"))

        # option: simulation.videoResolution
        # description: the size of the video every simulation run is asked to
        #              record, beside its before and after pictures: a name --
        #              'hd' or '720p' (1280x720), 'fhd' or '1080p' (1920x1080),
        #              '480p', 'qhd' or '1440p', '4k', 'uhd' or '2160p' -- a
        #              height alone ('1080', sixteen by nine), '<width>x<height>',
        #              or 'none' for no video at all. It is read, and anything
        #              it cannot make sense of reported, by
        #              'partcad.simulation.video_request'. The frame rate is 25
        #              and the viewpoint the scene's own 'render: png:' one,
        #              as for the pictures.
        # values: <string>
        # default: hd
        self.bind_env("simulation.videoResolution", "PC_SIMULATION_VIDEO_RESOLUTION")
        self.simulation_video_resolution = self.get("simulation.videoResolution")

        # option: telemetry
        # description: Telemetry configuration
        # values: <dict>
        # default: {
        #   "type": "sentry",
        #   "detail": "actions",
        #   "environment": "prod",
        #   "performance": "true",
        #   "failures": "true",
        #   "debug": "false",
        #   "sentry_dsn": "<PartCAD's default DSN>",
        #   "sentry_shutdown_timeout": "3.0",
        #   "sentry_attach_stacktrace": "false",
        #   "sentry_traces_sample_rate": "1.0",
        # }
        self.telemetry_config = TelemetryConfig(self)

        # option: git
        # description: Git configuration
        # values: <dict>
        # default: {}
        self.git_config = GitConfig(self)

        # option: git.auth
        # description: Credentials for private Git dependencies, keyed by host
        #              (or "default"). PartCAD never prompts for credentials --
        #              a prompt in a background daemon or a CI job is a hang --
        #              so they are configured here, upfront:
        #                git:
        #                  auth:
        #                    github.com:
        #                      username: <user>          # HTTPS
        #                      password: <token>         # a PAT, not a password
        #                      sshKey: ~/.ssh/id_work    # SSH
        #                      sshKeyPassphrase: <pass>
        # values: <dict>
        # default: {}
        self.git_auth = GitAuthConfig(self)

        # option: Personally identifiable information
        # description: Personally identifiable information configuration
        # values: <dict>
        # default: {}
        self.pii_config = PIIConfig(self)

        # option: Parameters
        # description: Object parameters configuration
        # values: <dict>
        # default: {}
        self.parameter_config = ParametersConfig(self)

        # option: offline
        # description: offline mode
        # values: [True | False]
        # default: False
        # The read has to come after the binding, not before it: assigning the
        # default first and binding afterwards left 'PC_OFFLINE' bound to a key
        # nothing ever looked up, so the variable had no effect at all outside
        # the CLI (which sets this attribute from its own '--offline' option).
        self.set_default("offline", False)
        self.bind_env("offline", "PC_OFFLINE")
        self.offline = self.get_bool("offline")

        # option: useDocker
        # description: whether PartCAD may use Docker at all. The master switch
        #              over every "useDocker*" option below: turning this off
        #              turns all of them off, whatever they say, which is what
        #              lets a machine with no Docker say so once instead of once
        #              per subject.
        # values: [True | False]
        # default: True
        #
        # Bound to the environment like every other option here, and it is the
        # one in this family a machine most needs to be able to answer without
        # writing a configuration file: an image built with no Docker in it -- a
        # cloud agent's container, a CI runner with no socket -- can say so once
        # in its environment, and everything that would otherwise fail against a
        # daemon that was never there can tell "there is none" from "there is
        # none and nobody said so", which are different situations and deserve
        # different outcomes.
        self.bind_env("useDocker", "PC_USE_DOCKER")
        self.use_docker = self.get_bool("useDocker")

        # option: useDockerPython
        # description: use a Docker container for running Python scripts
        # values: [True | False]
        # default: False
        #
        # Two attributes, because two questions have different answers and both
        # are asked: '*_declared' is what the configuration says (which is what
        # the 'useDockerPython' tag reports, so that a package can tell "not
        # asked for" from "asked for but unavailable"), and the plain attribute
        # is what actually happens once 'useDocker' has had its say.
        self.bind_env("useDockerPython", "PC_USE_DOCKER_PYTHON")
        self.use_docker_python_declared = self.get_bool("useDockerPython")
        self.use_docker_python = self.use_docker and self.use_docker_python_declared

        # option: useDockerKicad
        # description: use a Docker container for KiCad
        # values: [True | False]
        # default: True
        self.bind_env("useDockerKicad", "PC_USE_DOCKER_KICAD")
        self.use_docker_kicad_declared = self.get_bool("useDockerKicad")
        self.use_docker_kicad = self.use_docker and self.use_docker_kicad_declared

        # option: useDockerRemote
        # description: the Docker daemon PartCAD starts containers on cannot see
        #              this machine's files -- it runs on another machine, or
        #              behind DOCKER_HOST -- so files are sent to every container
        #              with each command, and what it writes is sent back, rather
        #              than being bind-mounted. Applies to every container
        #              PartCAD starts: the 'docker' Python sandbox, KiCad, a
        #              plugin's 'container:' and 'pc ide open'. See
        #              'partcad_utils.containers'.
        # values: [True | False]
        # default: False
        self.bind_env("useDockerRemote", "PC_USE_DOCKER_REMOTE")
        self.use_docker_remote = self.get_bool("useDockerRemote")

        # option: tags
        # description: extra tags to add to the ones PartCAD works out about
        #              this machine (its architecture, its operating system and
        #              that system's version). A package, or one of its objects,
        #              may name the tags it does not work under ("unless:") and
        #              is then skipped wherever one of them applies. This is how
        #              a user states something PartCAD cannot see for itself -
        #              that this host has no Docker, that this is the build
        #              machine, that KiCad is not installed here.
        # values: a list of tags, or a string of them separated by commas or
        #         whitespace (which is what PC_TAGS has to carry)
        # default: none
        #
        # The tags PartCAD derives are NOT here: they are a property of the
        # machine the work runs on, and are worked out there. This option is
        # user intent, so it travels with the rest of the configuration - a
        # daemon serving this caller honours the tags the caller declared.
        self.bind_env("tags", "PC_TAGS")
        self.tags = self.get("tags")

        # option: caeFeaImplementation
        # description: which implementation runs "pc cae fea", as
        #              "<package>:<file type>"
        # values: <string>
        # default: //pub/feature/cae/calculix:fea
        #
        # option: caeDynamicImplementation
        # description: which implementation runs "pc cae dynamic", as
        #              "<package>:<file type>"
        # values: <string>
        # default: //pub/feature/cae/elmer:dynamic
        #
        # option: caeThermalImplementation
        # description: which implementation runs "pc cae thermal", as
        #              "<package>:<file type>"
        # values: <string>
        # default: //pub/feature/cae/elmer:thermal
        #
        # option: caeCfdImplementation
        # description: which implementation runs "pc cae cfd", as
        #              "<package>:<file type>"
        # values: <string>
        # default: //pub/feature/cae/openfoam:cfd
        #
        # PartCAD ships no solver, so unlike every export and render format
        # there is no built-in implementation for these four to fall back on -
        # the default is a package in the public index, and this is where it is
        # named. It is user configuration rather than a constant because the
        # answer is a property of the machine and the person: which solver is
        # installed, which one is licensed, which one this shop trusts. A run
        # overrides it with "pc cae fea --implementation", and the IDE's FEA tab
        # with the field over the model.
        #
        # Defaulted here rather than only on the attribute, so that the resolved
        # value travels to the daemon like every other option: a key missing
        # from the copy is a key the daemon resolves from its own environment,
        # which is exactly what sending the configuration is meant to stop.
        #
        # One loop over the analyses rather than a block per option, so that the
        # option, its environment variable and the attribute
        # 'cae_implementation()' reads cannot be spelt three ways for one
        # analysis: 'dynamic' is 'caeDynamicImplementation',
        # 'PC_CAE_DYNAMIC_IMPLEMENTATION' and 'cae_dynamic_implementation'.
        for analysis, default in DEFAULT_CAE_IMPLEMENTATIONS.items():
            option = "cae%sImplementation" % analysis.capitalize()
            self.set_default(option, default)
            self.bind_env(option, "PC_CAE_%s_IMPLEMENTATION" % analysis.upper())
            # The 'or' still stands: a configuration file may carry the key
            # with nothing under it, and an analysis with no implementation at
            # all is a worse answer than the default one.
            setattr(self, "cae_%s_implementation" % analysis, self.get_string(option) or default)

        # option: camImplementation
        # description: which implementation produces a route for "pc cam", as
        #              "<package>:<file type>"
        # values: <string>
        # default: //builtin/cam:gcode
        #
        # Unlike the four above there *is* a built-in to fall back on, and the
        # default names it. What this option is for is the machine at the other
        # end: a controller that wants a dialect of its own, or a shop with a
        # post-processor it already trusts, is a package declaring a file type
        # in its own 'cam:' section and this option pointing at it. A run
        # overrides it with "pc cam --implementation", and an object with
        # "implementation:" in its own 'cam:' section.
        self.set_default("camImplementation", DEFAULT_CAM_IMPLEMENTATION)
        self.bind_env("camImplementation", "PC_CAM_IMPLEMENTATION")
        self.cam_implementation = self.get_string("camImplementation") or DEFAULT_CAM_IMPLEMENTATION

    def cae_implementation(self, analysis: str) -> str:
        """Which implementation runs one analysis, by its name ("fea", "cfd", ...).

        Looked up rather than branched on, so that adding a third analysis is an
        entry in 'DEFAULT_CAE_IMPLEMENTATIONS' and an option key beside it, and
        not a chain of ifs in whatever asks.
        """
        attribute = "cae_%s_implementation" % analysis
        if not hasattr(self, attribute):
            raise ValueError("PartCAD does not run a '%s' analysis" % analysis)
        return getattr(self, attribute)


user_config = UserConfig()
