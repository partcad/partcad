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
from pathlib import Path
import shutil
import vyper

from . import logging as pc_logging

# IMPORTANT:
# We need to maintain setting default values in both the CLI and the user_config, because of:
# 1) CLI needs default values to show them to the user
# 2) CLI pushes the default values to user_config unconditionally (if no user values are set)
# 3) user_config is used outside of CLI, where CLI default values are not available

pc_logging.logging.getLogger("vyper").propagate = False
pc_logging.logging.getLogger("vyper").setLevel(pc_logging.logging.ERROR)
pc_logging.logging.getLogger("vyper").addHandler(pc_logging.logging.NullHandler())


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


class ApiKeyConfig(BaseConfig):
    def __init__(self, v):
        super().__init__(v, "apiKey")


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


# TODO(clairbee): moake TelemetryConfig a subclass of BaseConfig
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
        if self.v.is_set("telemetry.type"):
            return self.v.get_string("telemetry.type")

        return "sentry"

    @property
    def env(self):
        if self.v.is_set("telemetry.env"):
            return self.v.get_string("telemetry.env")

        from . import __spec__

        # If the module is loaded from a file, then we are in development mode
        if __spec__.loader.__class__.__name__ == "SourceFileLoader":
            return "dev"
        else:
            return "prod"

    @property
    def performance(self):
        if self.v.is_set("telemetry.performance"):
            return self.v.get_bool("telemetry.performance")
        return True

    @property
    def failures(self):
        if self.v.is_set("telemetry.failures"):
            return self.v.get_bool("telemetry.failures")
        return True

    @property
    def debug(self):
        if self.v.is_set("telemetry.debug"):
            return self.v.get_bool("telemetry.debug")
        return False

    @property
    def sentry_dsn(self):
        if self.v.is_set("telemetry.sentryDsn"):
            return self.v.get_string("telemetry.sentryDsn")

        # TODO(clairbee): create a load balancer for Sentry
        # return "https://sentry.partcad.org"
        return "https://3a80dc66ff544e5000cb4c50751f0eca@o4508651588485120.ingest.us.sentry.io/4508651601526784"

    @property
    def sentry_shutdown_timeout(self):
        if self.v.is_set("telemetry.sentryShutdownTimeout"):
            return self.v.get_float("telemetry.sentryShutdownTimeout")
        return 3.0

    @property
    def sentry_attach_stacktrace(self):
        if self.v.is_set("telemetry.sentryAttachStacktrace"):
            return self.v.get_bool("telemetry.sentryAttachStacktrace")
        return False

    @property
    def sentry_traces_sample_rate(self):
        if self.v.is_set("telemetry.sentryTracesSampleRate"):
            return self.v.get_float("telemetry.sentryTracesSampleRate")
        return 1.0

    def __repr__(self):
        properties = []
        for name, val in vars(TelemetryConfig).items():
            if isinstance(val, property):
                properties.append((name, val.__get__(self, TelemetryConfig)))
        return str({k: v for k, v in properties})


class UserConfig(vyper.Vyper):
    @staticmethod
    def get_config_dir():
        home = os.environ.get("HOME", Path.home())
        return os.path.join(home, ".partcad")

    @staticmethod
    def get_cache_dir():
        return os.path.join(Path.home(), ".cache", "partcad")

    def __init__(self):
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
        self.set_default("cacheFiles", True)
        self.set_default("cacheFilesMaxEntrySize", 10 * 1024 * 1024)
        self.set_default("cacheFilesMinEntrySize", 100)
        self.set_default("cacheMemoryMaxEntrySize", 100 * 1024 * 1024)
        self.set_default("cacheMemoryDoubleCacheMaxEntrySize", 1 * 1024 * 1024)
        self.set_default("cacheDependenciesIgnore", False)

        if shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("pythonSandbox", "conda")
        else:
            self.set_default("pythonSandbox", "none")

        self.set_default("internalStateDir", UserConfig.get_config_dir())
        self.set_default("forceUpdate", False)

        self.set_default("useDockerPython", False)
        self.set_default("useDockerKicad", True)

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

        # option: internalStateDir
        # description: folder to store all temporary files
        # values: <path>
        # default: '.partcad' folder in the home directory
        self.bind_env("internalStateDir", "PC_INTERNAL_STATE_DIR")
        self.internal_state_dir = self.get_string("internalStateDir")

        # option: forceUpdate
        # description: update all repositories even if they are fresh
        # values: [True | False]
        # default: False
        self.bind_env("forceUpdate", "PC_FORCE_UPDATE")
        self.force_update = self.get_bool("forceUpdate")

        # option: googleApiKey
        # description: GOOGLE API key for AI services
        # values: <string>
        # default: None
        self.bind_env("googleApiKey", "PC_GOOGLE_API_KEY")
        self.google_api_key = self.get("googleApiKey")

        # option: openaiApiKey
        # description: OpenAI API key for AI services
        # values: <string>
        # default: None
        self.bind_env("openaiApiKey", "PC_OPENAI_API_KEY")
        self.openai_api_key = self.get("openaiApiKey")

        # option: ollamaNumThread
        # description: Ask Ollama to use the given number of CPU threads
        # values: <integer>
        # default: None
        self.ollama_num_thread = None
        self.bind_env("ollamaNumThread", "PC_OLLAMA_NUM_THREAD")
        if self.is_set("ollamaNumThread"):
            self.ollama_num_thread = self.get_int("ollamaNumThread")

        # option: maxGeometricModeling
        # description: the number of attempts for geometric modelling
        # values: <integer>
        # default: None
        self.max_geometric_modeling = None
        self.bind_env("maxGeometricModeling", "PC_MAX_GEOMETRIC_MODELING")
        if self.is_set("maxGeometricModeling"):
            self.max_geometric_modeling = self.get_int("maxGeometricModeling")

        # option: maxModelGeneration
        # description: the number of attempts for CAD script generation
        # values: <integer>
        # default: None
        self.max_model_generation = None
        self.bind_env("maxModelGeneration", "PC_MAX_MODEL_GENERATION")
        if self.is_set("maxModelGeneration"):
            self.max_model_generation = self.get_int("maxModelGeneration")

        # option: maxScriptCorrection
        # description: the number of attempts to incrementally fix the script if it's not working
        # values: <integer>
        # default: None
        self.max_script_correction = None
        self.bind_env("maxScriptCorrection", "PC_MAX_SCRIPT_CORRECTION")
        if self.is_set("maxScriptCorrection"):
            self.max_script_correction = self.get_int("maxScriptCorrection")

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

        # option: Provider Key
        # description: Provider Key configuration
        # values: <dict>
        # default: {}
        self.api_key = ApiKeyConfig(self)

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
        self.offline = False
        self.bind_env("offline", "PC_OFFLINE")

        # option: useDockerPython
        # description: use a Docker container for running Python scripts
        # values: [True | False]
        # default: False
        self.use_docker_python = self.get_bool("useDockerPython")

        # option: useDockerKicad
        # description: use a Docker container for KiCad
        # values: [True | False]
        # default: True
        self.use_docker_kicad = self.get_bool("useDockerKicad")


user_config = UserConfig()
