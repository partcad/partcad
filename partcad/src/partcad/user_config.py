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


class UserConfig(vyper.Vyper):
    @staticmethod
    def get_config_dir():
        return os.path.join(Path.home(), ".partcad")

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

        if shutil.which("conda") is not None or importlib.util.find_spec("conda") is not None:
            self.set_default("pythonSandbox", "conda")
        else:
            self.set_default("pythonSandbox", "none")

        self.set_default("internalStateDir", UserConfig.get_config_dir())
        self.set_default("forceUpdate", False)

        self.set_default("sentry.shutdown_timeout", 5)
        self.set_default("sentry.traces_sample_rate", 1.0)
        self.set_default("sentry.dsn", "https://sentry.partcad.org")
        self.set_default("sentry.environment", "production")
        self.set_default("sentry.debug", False)
        self.set_default("sentry.enable_tracing", True)
        self.set_default("sentry.attach_stacktrace", False)

        self.set_env_prefix("pc")
        self.automatic_env()

        # option: threadsMax
        # description: the maximum number of processing threads to use (not a strict limit)
        # values: >2
        # default: min(7, <cpu threads count - 1>)
        self.threads_max = None
        if self.is_set("threadsMax"):
            self.threads_max = self.get_int("threadsMax")

        # option: pythonSandbox
        # description: sandboxing environment for invoking python scripts
        # values: [none | pypy | conda]
        # default: conda
        self.python_runtime = self.get("pythonSandbox")

        # option: internalStateDir
        # description: folder to store all temporary files
        # values: <path>
        # default: '.partcad' folder in the home directory
        self.internal_state_dir = self.get("internalStateDir")

        # option: forceUpdate
        # description: update all repositories even if they are fresh
        # values: [True | False]
        # default: False
        self.force_update = self.get_bool("forceUpdate")

        # option: googleApiKey
        # description: GOOGLE API key for AI services
        # values: <string>
        # default: None
        self.google_api_key = self.get("googleApiKey")

        # option: openaiApiKey
        # description: OpenAI API key for AI services
        # values: <string>
        # default: None
        self.openai_api_key = self.get("openaiApiKey")

        # option: ollamaNumThread
        # description: Ask Ollama to use the given number of CPU threads
        # values: <integer>
        # default: None
        self.ollama_num_thread = None
        if self.is_set("ollamaNumThread"):
            self.ollama_num_thread = self.get_int("ollamaNumThread")

        # option: maxGeometricModeling
        # description: the number of attempts for geometric modelling
        # values: <integer>
        # default: None
        self.max_geometric_modeling = None
        if self.is_set("maxGeometricModeling"):
            self.max_geometric_modeling = self.get_int("maxGeometricModeling")

        # option: maxModelGeneration
        # description: the number of attempts for CAD script generation
        # values: <integer>
        # default: None
        self.max_model_generation = None
        if self.is_set("maxModelGeneration"):
            self.max_model_generation = self.get_int("maxModelGeneration")

        # option: maxScriptCorrection
        # description: the number of attempts to incrementally fix the script if it's not working
        # values: <integer>
        # default: None
        self.max_script_correction = None
        if self.is_set("maxScriptCorrection"):
            self.max_script_correction = self.get_int("maxScriptCorrection")


user_config = UserConfig()
