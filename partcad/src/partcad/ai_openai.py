#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

import base64
import importlib
import mimetypes
from pathlib import Path
import re
import threading
from typing import Any

# Lazy-load AI imports as they are not always needed
# import openai as openai_genai
openai_genai = None

from . import logging as pc_logging
from .user_config import user_config

lock = threading.Lock()
OPENAI_API_KEY = None
openai_client = None

model_tokens = {
    "gpt-3": 4000,
    "gpt-3.5-turbo": 4096,
    "gpt-4": 8000,  # 32600,
    "gpt-4-vision-preview": 8192,
    "gpt-4o": 16000,  # 32600,
    "gpt-4o-mini": 16000,  # 32600,
}


def openai_once():
    global OPENAI_API_KEY, openai_client, openai_genai

    with lock:
        if openai_genai is None:
            openai_genai = importlib.import_module("openai")

        latest_key = user_config.openai_api_key
        if latest_key != OPENAI_API_KEY:
            OPENAI_API_KEY = latest_key
            if not OPENAI_API_KEY is None:
                openai_genai.api_key = OPENAI_API_KEY
                openai_client = openai_genai.OpenAI(api_key=OPENAI_API_KEY)
                return True

        if OPENAI_API_KEY is None:
            raise Exception("OpenAI API key is not set")

    return True


class AiOpenAI:
    def generate_openai(
        self,
        model: str,
        prompt: str,
        config: dict[str, Any] = {},
        options_num: int = 1,
    ):
        if not openai_once():
            return None

        if "tokens" in config:
            tokens = config["tokens"]
        else:
            tokens = model_tokens[model]

        if "top_p" in config:
            top_p = config["top_p"]
        else:
            top_p = None

        if "temperature" in config:
            temperature = config["temperature"]
        else:
            temperature = None

        pc_logging.debug("Prompt: %s", prompt)

        image_content = []

        def insert_image(match):
            filename = match.group(1)
            image_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:%s;base64,%s"
                        % (
                            mimetypes.guess_type(filename, False)[0],
                            base64.b64encode(Path(filename).read_bytes()).decode(),
                        ),
                        "detail": "high",
                    },
                }
            )
            return "IMAGE_INSERTED_HERE"

        prompt = re.sub(r"INSERT_IMAGE_HERE\(([^)]*)\)", insert_image, prompt)
        text_content = list(
            map(
                lambda prompt_section: {"type": "text", "text": prompt_section},
                prompt.split("IMAGE_INSERTED_HERE"),
            )
        )

        content = []
        for i in range(len(text_content)):
            content.append(text_content[i])
            if i < len(image_content):
                content.append(image_content[i])

        params = {
            "messages": [
                {"role": "user", "content": content},
            ],
            "stream": False,
            "n": options_num,
            "model": model,
        }
        if model.startswith("o1"):
            # params["max_completion_tokens"] = tokens
            pass
        else:
            params["max_tokens"] = tokens
            params["temperature"] = temperature
            params["top_p"] = top_p
        cc = openai_client.chat.completions.create(
            **params,
        )

        products = []
        try:
            for choice in cc.choices:
                if hasattr(choice, "role") and choice.role == "system":
                    continue

                script = choice.message.content

                products.append(script)
        except Exception as e:
            pc_logging.exception(e)

        return products
