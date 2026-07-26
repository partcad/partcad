#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

import fnmatch
import time

from . import telemetry
from .ai_google import AiGoogle
from .ai_openai import AiOpenAI
from .ai_ollama import AiOllama

from . import logging as pc_logging
from .user_config import user_config


supported_models = [
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1*",
    "gpt-5*",
    "o3*",
    "o4*",
    # Gemini 1.x and the original "gemini-pro"/"gemini-pro-vision" aliases have
    # been retired by Google. Match the live 2.x/3.x families by pattern so new
    # point releases do not need a code change.
    "gemini-2.*",
    "gemini-3.*",
    "gemini-*-latest",
    "llama3.*",
    "codellama*",
    "codegemma*",
    "gemma*",
    "deepseek-coder*",
    "codestral*",
]

# The model used when the user picked a provider but not a model.
# Keep in sync with `shape_ai.py` and `docs/source/configuration.rst`.
DEFAULT_GOOGLE_MODEL = "gemini-2.5-pro"
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OLLAMA_MODEL = "llama3.1:70b"


@telemetry.instrument()
class Ai(AiGoogle, AiOpenAI, AiOllama):
    def generate(
        self,
        action: str,
        package: str,
        item: str,
        prompt: str,
        config: dict[str, str],
        num_options: int = 1,
    ):
        with pc_logging.Action("Ai" + action, package, item):
            # Determine the model to use
            provider = config.get("provider", None)
            if "model" in config and config["model"] is not None and config["model"] != "":
                model = config["model"]
            else:
                if provider is None:
                    if not user_config.openai_api_key is None:
                        provider = "openai"
                    else:
                        provider = "google"

                if provider == "google":
                    model = DEFAULT_GOOGLE_MODEL
                elif provider == "openai":
                    model = DEFAULT_OPENAI_MODEL
                elif provider == "ollama":
                    model = DEFAULT_OLLAMA_MODEL
                else:
                    error = "Provider %s is not supported" % provider
                    pc_logging.error(error)
                    return []

            # Generate the content
            is_supported = False
            for supported_model_pattern in supported_models:
                if fnmatch.fnmatch(model, supported_model_pattern):
                    is_supported = True
                    break
            if not is_supported:
                error = "Model %s is not supported" % model
                pc_logging.error(error)
                return []

            self.model = model
            result = []
            if provider == "google":
                try:
                    result = self.generate_google(
                        model,
                        prompt,
                        config,
                        num_options,
                    )
                except Exception as e:
                    pc_logging.error("Failed to generate with Google: %s" % str(e))
                    time.sleep(1)  # Safeguard against exceeding quota

            elif provider == "openai":
                try:
                    result = self.generate_openai(
                        model,
                        prompt,
                        config,
                        num_options,
                    )
                except Exception as e:
                    pc_logging.error("Failed to generate with OpenAI: %s" % str(e))
                    time.sleep(1)  # Safeguard against exceeding quota

            elif provider == "ollama":
                try:
                    result = self.generate_ollama(
                        model,
                        prompt,
                        config,
                        num_options,
                    )
                except Exception as e:
                    pc_logging.error("Failed to generate with Ollama: %s" % str(e))

            else:
                pc_logging.error("Failed to associate the model %s with the provider" % model)

            if result is None:
                return []
            return result
