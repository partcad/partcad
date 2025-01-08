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

# Lazy-load AI imports as they are not always needed
# import ollama
ollama = None

from . import logging as pc_logging
from .user_config import user_config

lock = threading.Lock()

model_tokens = {}

ollama_num_thread = None

models_pulled = {}


def ollama_once():
    global ollama, ollama_num_thread

    with lock:
        if ollama is None:
            ollama = importlib.import_module("ollama")

            ollama_num_thread = user_config.ollama_num_thread

    return True


def model_once(model: str):
    global models_pulled

    ollama_once()

    with lock:
        if not model in models_pulled:
            with pc_logging.Action("OllamaPull", model):
                ollama.pull(model)
                models_pulled[model] = True


class AiOllama:
    def generate_ollama(
        self,
        model: str,
        prompt: str,
        config: dict[str, Any] = {},
        options_num: int = 1,
    ):
        model_once(model)

        pc_logging.info("Generating with Ollama: asking for %d alternatives", options_num)

        if not ollama_once():
            return None

        image_content = []

        def insert_image(match):
            filename = match.group(1)
            image_index = len(image_content)
            image_content.append(
                Path(filename).read_bytes(),
                # base64.b64encode(Path(filename).read_bytes()).decode(),
            )
            return f"The attached image number {image_index}.\n"

        prompt = re.sub(r"INSERT_IMAGE_HERE\(([^)]*)\)", insert_image, prompt)

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
                    pc_logging.debug("Images: %d" % len(image_content))
                    response = ollama.generate(
                        model=model,
                        context=[],  # do not accumulate context uncontrollably
                        prompt=prompt,
                        images=image_content,
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
