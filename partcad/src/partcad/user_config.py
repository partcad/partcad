#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import importlib.util
import os
from pathlib import Path
import shutil
import vyper

from . import logging as pc_logging


class SentryConfig:
    def __init__(self, v):
        self.v: vyper.Vyper = v

    @property
    def dsn(self):
        if self.v.is_set("sentry.dsn"):
            return self.v.get("sentry.dsn")

    @property
    def debug(self):
        if self.v.is_set("sentry.debug"):
            return self.v.get_bool("sentry.debug")
        return False

    @property
    def shutdown_timeout(self):
        if self.v.is_set("sentry.shutdown_timeout"):
            return self.v.get_int("sentry.shutdown_timeout")
        return 20

    @property
    def traces_sample_rate(self):
        if self.v.is_set("sentry.traces_sample_rate"):
            return self.v.get_float("sentry.traces_sample_rate")
        return 0.85

    def __repr__(self):
        properties = []
        for name, val in vars(SentryConfig).items():
            if isinstance(val, property):
                properties.append((name, val.__get__(self, SentryConfig)))
        return str({k: v for k, v in properties if v is not None})


class GitConfig(dict):
    def __init__(self, v):
        self._v: vyper.Vyper = v

    @property
    def _config(self):
        config = self._v.get("git.config")
        if config is None:
            config = {}
        return config

    def __getattr__(self, item):
        return self._config.get(item)

    def __getitem__(self, item):
        return self._config.get(item)

    def __iter__(self):
        return iter(self._config)

    def __len__(self):
        return len(self._config)

    def __repr__(self):
        return str(self._config)


class UserConfig(vyper.Vyper):
    @staticmethod
    def get_config_dir():
        home = os.environ.get("HOME", Path.home())
        return os.path.join(home, ".partcad")

    def __init__(self):
        super().__init__()
        self.set_config_type("yaml")

        config_path = os.path.join(
            UserConfig.get_config_dir(),
            "config.yaml",
        )
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    self.read_config(f)
            except Exception as e:
                pc_logging.error("ERROR: Failed to parse %s" % config_path)

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

        # option: sentry
        # description: Sentry configuration
        # values: <dict>
        # default: {"debug": "false", "shutdown_timeout": "5", "traces_sample_rate": "1.0"}
        self.sentry_config = SentryConfig(self)
        self.bind_env("sentry.dsn", "PC_SENTRY_DSN")
        self.bind_env("sentry.debug", "PC_SENTRY_DEBUG")
        self.bind_env("sentry.shutdown_timeout", "PC_SENTRY_SHUTDOWN_TIMEOUT")
        self.bind_env("sentry.traces_sample_rate", "PC_SENTRY_TRACES_SAMPLE_RATE")

        # option: git
        # description: Git configuration
        # values: <dict>
        # default: {}
        self.git_config = GitConfig(self)


user_config = UserConfig()
