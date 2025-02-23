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


SUPPORTED_MODELS = [
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
    def __init__(self, ai_config: dict):
        """
        Initialize the AI generator with a unified configuration.
        The configuration should contain at least a provider and model (or allow defaults).
        """
        self.ai_config = ai_config or {}
        self.provider, self.model, self.parameters = self._resolve_config(self.ai_config)
        if not self.provider or not self.model:
            raise ValueError("Invalid AI configuration: provider and model must be set.")
        pc_logging.debug(
            f"Initialized AI: provider={self.provider}, model={self.model}, parameters={self.parameters}"
        )

    def _resolve_config(self, config: dict):
        """
        Resolves the provider, model, and parameters from the given configuration.
        If the model is not explicitly provided, default values are used based on the provider
        or availability of API keys.
        """
        provider = config.get("provider")
        model = config.get("model")
        parameters = config.get("parameters", {})

        if not model:
            # Set a default model based on the provider if model is not specified.
            if provider == "google":
                model = "gemini-1.5-pro"
            elif provider == "openai":
                model = "gpt-4o"
            elif provider == "ollama":
                model = "llama3.1:70b"
            else:
                # Determine provider based on available API keys if not provided.
                provider = "openai" if user_config.openai_api_key else "google"
                model = "gpt-4o" if provider == "openai" else "gemini-1.5-pro"
        return provider, model, parameters

    def generate(
        self,
        action: str,
        package: str,
        item: str,
        prompt: str,
        num_options: int = 1,
    ) -> list:
        """
        Generate content using the configured AI provider.
        This unified interface makes AI generation work just like downloading a script
        from a URL—no dedicated file types.
        """
        with pc_logging.Action("Ai" + action, package, item):
            # Verify the selected model against supported patterns.
            if not any(fnmatch.fnmatch(self.model, pattern) for pattern in SUPPORTED_MODELS):
                pc_logging.error(f"Model '{self.model}' is not supported.")
                return []

            pc_logging.info(f"Using AI Provider: {self.provider}, Model: {self.model}")

            try:
                if self.provider == "google":
                    result = self.generate_google(self.model, prompt, self.ai_config, num_options)
                elif self.provider == "openai":
                    result = self.generate_openai(self.model, prompt, self.ai_config, num_options)
                elif self.provider == "ollama":
                    result = self.generate_ollama(self.model, prompt, self.ai_config, num_options)
                else:
                    pc_logging.error(f"Unknown provider: {self.provider}")
                    return []
            except Exception as e:
                pc_logging.error(f"Failed to generate with {self.provider}: {str(e)}")
                time.sleep(1)  # Safeguard against issues such as exceeding quota.
                return []

            return result if result is not None else []
