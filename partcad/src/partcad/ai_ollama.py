#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-08-24
#
# Licensed under Apache License, Version 2.0.
#

import base64
import importlib
import httpx
from pathlib import Path
import re
import threading
import time
from typing import Any

from .ai_feature_file import AiContentFile, AiContentProcessor
from . import logging as pc_logging

# Lazy-load AI imports as they are not always needed
# import ollama
ollama = None

lock = threading.Lock()

model_tokens = {}

ollama_num_thread = None

models_pulled = {}


def ollama_once(num_thread):
    global ollama, ollama_num_thread

    with lock:
        if ollama is None:
            ollama = importlib.import_module("ollama")

            ollama_num_thread = num_thread

    return True


def model_once(model: str, num_thread):
    global models_pulled

    ollama_once(num_thread)

    with lock:
        if not model in models_pulled:
            with pc_logging.Action("OllamaPull", model):
                ollama.pull(model)
                models_pulled[model] = True


class AiOllama(AiContentProcessor):
    def generate_ollama(
        self,
        model: str,
        prompt: str,
        config: dict[str, Any] = {},
        options_num: int = 1,
    ):
        model_once(model, self.ctx.user_config.ollama_num_thread)

        pc_logging.info("Generating with Ollama: asking for %d alternatives", options_num)

        if not ollama_once():
            return None

        def handle_content(content: AiContentFile):
            return Path(content.filename).read_bytes()

        content_parts, content_inserts = self.process_content(prompt)
        content_inserts = list(map(handle_content, content_inserts))
        prompt = ""
        for i in range(len(content_parts)):
            prompt += content_parts[i]
            if i < len(content_inserts):
                prompt += f"This file is attached at the index of {i}.\n"

        if "tokens" in config:
            tokens = config["tokens"]
        else:
            tokens = model_tokens[model] if model in model_tokens else None

        if "top_p" in config:
            top_p = config["top_p"]
        else:
            top_p = None

        if "top_k" in config:
            top_k = config["top_k"]
        else:
            top_k = None

        if "temperature" in config:
            temperature = config["temperature"]
        else:
            temperature = None

        candidates = []
        for _ in range(options_num):
            retry = True
            while retry == True:
                retry = False
                try:
                    options = ollama.Options(
                        tokens=tokens,
                        num_thread=ollama_num_thread,
                        top_p=top_p,
                        top_k=top_k,
                        temperature=temperature,
                    )
                    pc_logging.debug("Prompt: %s" % prompt)
                    pc_logging.debug("Files: %d" % len(content_inserts))
                    response = ollama.generate(
                        model=model,
                        context=[],  # do not accumulate context uncontrollably
                        prompt=prompt,
                        images=content_inserts,
                        options=options,
                    )
                except httpx.ConnectError as e:
                    pc_logging.exception(e)
                    pc_logging.error("Failed to connect to Ollama. Is it running?")
                    retry = True
                    time.sleep(15)
                except ollama._types.ResponseError as e:
                    pc_logging.exception(e)
                    pc_logging.error("Failed to generate with Ollama: %s" % str(e))
                    pc_logging.warning(f"Consider running 'ollama run {model}' first...")
                    if "not found" in str(e):
                        retry = True
                        time.sleep(15)
                    else:
                        time.sleep(1)
                except Exception as e:
                    pc_logging.exception(e)
                    retry = True
                    time.sleep(1)

            if not response or not "response" in response:
                error = "%s: Failed to generate content" % self.name
                pc_logging.error(error)
                return

            pc_logging.info("Response: %s", str(response))
            # Perform Ollama-specific output sanitization
            response_text = response["response"]
            response_text = response_text.replace("\\'", "'")
            candidates.append(response_text)

        products = []
        try:
            for candidate in candidates:
                if candidate:
                    products.append(candidate)
        except Exception as e:
            pc_logging.exception(e)

        return products
