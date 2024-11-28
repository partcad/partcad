#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import importlib.util
import os
from pathlib import Path
import shutil
import yaml

from . import logging as pc_logging


class UserConfig:
    @staticmethod
    def get_config_dir():
        return os.path.join(Path.home(), ".partcad")

    def __init__(self):
        self.config_obj = {}

        config_path = os.path.join(
            UserConfig.get_config_dir(),
            "config.yaml",
        )
        if os.path.exists(config_path):
            try:
                self.config_obj = yaml.safe_load(open(config_path, "r"))
                if self.config_obj is None:
                    self.config_obj = {}
            except Exception as e:
                pc_logging.error("ERROR: Failed to parse %s" % config_path)

        # option: threadsMax
        # description: the maximum number of processing threads to use (not a strict limit)
        # values: >2
        # default: min(7, <cpu threads count - 1>)
        self.threads_max = None

        if "threadsMax" in self.config_obj:
            self.threads_max = int(self.config_obj["threadsMax"])

        # option: pythonSandbox
        # description: sandboxing environment for invoking python scripts
        # values: [none | pypy | conda]
        # default: conda
        if (
            not shutil.which("conda") is None
            or importlib.util.find_spec("conda") is not None
        ):
            self.python_runtime = "conda"
        else:
            self.python_runtime = "none"

        if "pythonSandbox" in self.config_obj:
            self.python_runtime = self.config_obj["pythonSandbox"]

        # option: internalStateDir
        # description: folder to store all temporary files
        # values: <path>
        # default: '.partcad' folder in the home directory
        if "internalStateDir" in self.config_obj:
            self.internal_state_dir = self.config_obj["internalStateDir"]
        else:
            self.internal_state_dir = UserConfig.get_config_dir()

        # option: forceUpdate
        # description: update all repositories even if they are fresh
        # values: [True | False]
        # default: False
        if "forceUpdate" in self.config_obj:
            self.force_update = self.config_obj["forceUpdate"]
        else:
            self.force_update = False

        # option: googleApiKey
        # description: GOOGLE API key for AI services
        # values: <string>
        # default: None
        if "googleApiKey" in self.config_obj:
            self.google_api_key = self.config_obj["googleApiKey"]
        else:
            self.google_api_key = None

        # option: openaiApiKey
        # description: OpenAI API key for AI services
        # values: <string>
        # default: None
        if "openaiApiKey" in self.config_obj:
            self.openai_api_key = self.config_obj["openaiApiKey"]
        else:
            self.openai_api_key = None

        # option: ollamaNumThread
        # description: Ask Ollama to use the given number of CPU threads
        # values: <integer>
        # default: None
        if "ollamaNumThread" in self.config_obj:
            self.ollama_num_thread = int(self.config_obj["ollamaNumThread"])
        else:
            self.ollama_num_thread = None

        # option: maxGeometricModeling
        # description: the number of attempts for geometric modelling
        # values: <integer>
        # default: None
        if "maxGeometricModeling" in self.config_obj:
            self.max_geometric_modeling = int(
                self.config_obj["maxGeometricModeling"]
            )
        else:
            self.max_geometric_modeling = None

        # option: maxModelGeneration
        # description: the number of attempts for CAD script generation
        # values: <integer>
        # default: None
        if "maxModelGeneration" in self.config_obj:
            self.max_model_generation = int(
                self.config_obj["maxModelGeneration"]
            )
        else:
            self.max_model_generation = None

        # option: maxScriptCorrection
        # description: the number of attempts to incrementally fix the script if it's not working
        # values: <integer>
        # default: None
        if "maxScriptCorrection" in self.config_obj:
            self.max_script_correction = int(
                self.config_obj["maxScriptCorrection"]
            )
        else:
            self.max_script_correction = None


user_config = UserConfig()
