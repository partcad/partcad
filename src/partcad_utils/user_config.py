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
import os
import shutil
from pathlib import Path

import vyper

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
    "pythonSandbox",
    "ignoreBundledOpenscad",
    "internalStateDir",
    "logLevel",
    "forceUpdate",
    "develIndex",
    "offline",
    "git.clone.timeout",
    "git.clone.retry.max",
    "git.clone.retry.patience",
    "useDocker",
    "useDockerPython",
    "useDockerKicad",
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


class UserConfig(vyper.Vyper):
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
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        """Rebuild a configuration from what :meth:`to_dict` produced."""
        return cls(settings=data)

    def __init__(self, settings: dict = None):
        super().__init__()
        self.set_config_type("yaml")

        cfg_dir = UserConfig.get_config_dir()
        os.makedirs(cfg_dir, exist_ok=True)
        config_path = os.path.join(
            cfg_dir,
            "config.yaml",
        )
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
        # - objects from 1MB bytes to 10MB are cached in the filesystem only (optimize RAM usage).
        # - objects from 10MB to 100MB are cached in memory only (avoid quick filesystem quota depletion).
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
        self.set_default("cacheFilesMaxEntrySize", 10 * 1024 * 1024)
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

        if shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("pythonSandbox", "conda")
        else:
            self.set_default("pythonSandbox", "none")

        # Unlike Python, whose sandbox has to be provisioned because PartCAD's
        # own interpreter is the wrong one to render in, a host Node.js is
        # simply used when there is one: it costs nothing, and the dependency
        # tree - which is what actually has to be isolated - is provisioned
        # either way. conda is the fallback, so a host without Node.js still
        # works if conda can supply one.
        if shutil.which("node") is not None:
            self.set_default("javascriptSandbox", "none")
        elif shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("javascriptSandbox", "conda")
        else:
            self.set_default("javascriptSandbox", "none")

        self.set_default("internalStateDir", UserConfig.get_config_dir())
        self.set_default("forceUpdate", False)
        self.set_default("develIndex", False)

        # option: git.clone.timeout
        # description: how long a single git network operation (clone, fetch,
        #              pull) may take before it is aborted, in seconds. Without
        #              a bound, an unreachable or stalled remote hangs partcad
        #              indefinitely; the clone retry logic does not help because
        #              a hang never raises GitCommandError.
        # values: <int>
        # default: 180
        self.set_default("git.clone.timeout", 180)

        self.set_default("useDocker", True)
        self.set_default("useDockerPython", False)
        self.set_default("useDockerKicad", True)
        self.set_default("tags", "")

        self.set_env_prefix("pc")

        # option: threadsMax
        # description: the maximum number of processing threads to use (not a strict limit)
        # values: >2
        # default: min(7, <cpu threads count - 1>)
        self.bind_env("threadsMax", "PC_THREADS_MAX")
        self.threads_max = None
        if self.is_set("threadsMax"):
            self.threads_max = self.get_int("threadsMax")

        # option: cacheFiles
        # description: enable caching of intermediate results to the filesystem
        # values: [True | False]
        # default: True
        self.bind_env("cacheFiles", "PC_CACHE_FILES")
        self.cache = self.get_bool("cacheFiles")

        # option: cacheFilesMaxEntrySize
        # description: the maximum size of a single file cache entry in bytes
        # values: >0
        # default: 10*1024*1024 (10MB)
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

        # option: pythonSandbox
        # description: sandboxing environment for invoking python scripts
        # values: [none | pypy | conda]
        # default: conda
        self.bind_env("pythonSandbox", "PC_PYTHON_SANDBOX")
        self.python_sandbox = self.get_string("pythonSandbox")

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
        # description: update all repositories even if they are fresh
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
        # values: [True | False]
        # default: False
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

        # option: telemetry
        # description: Telemetry configuration
        # values: <dict>
        # default: {
        #   "type": "sentry",
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
        self.use_docker_python_declared = self.get_bool("useDockerPython")
        self.use_docker_python = self.use_docker and self.use_docker_python_declared

        # option: useDockerKicad
        # description: use a Docker container for KiCad
        # values: [True | False]
        # default: True
        self.use_docker_kicad_declared = self.get_bool("useDockerKicad")
        self.use_docker_kicad = self.use_docker and self.use_docker_kicad_declared

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


user_config = UserConfig()
