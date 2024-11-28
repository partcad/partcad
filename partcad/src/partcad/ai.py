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

from .ai_google import AiGoogle
from .ai_openai import AiOpenAI
from .ai_ollama import AiOllama

from . import logging as pc_logging
from .user_config import user_config


supported_models = [
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "o1-*",
    "gemini-pro",
    "gemini-pro-vision",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "llama3.*",
    "codellama*",
    "codegemma*",
    "gemma*",
    "deepseek-coder*",
    "codestral*",
]


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
                    # if len(image_filenames) > 0:
                    #     model = "gemini-pro-vision"
                    # else:
                    #     model = "gemini-pro"
                    model = "gemini-1.5-pro"
                elif provider == "openai":
                    # if len(image_filenames) > 0:
                    #     model = "gpt-4o"
                    # else:
                    #     model = "gpt-4o"
                    model = "gpt-4o"
                elif provider == "ollama":
                    model = "llama3.1:70b"
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
