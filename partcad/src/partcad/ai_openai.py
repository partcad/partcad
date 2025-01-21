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

from .sentry import instrument
from .ai_feature_file import AiContentFile, AiContentProcessor
from . import logging as pc_logging
from .user_config import user_config

# Lazy-load AI imports as they are not always needed
# import openai as openai_genai
openai_genai = None

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


@instrument()
class AiOpenAI(AiContentProcessor):
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

        def handle_content(content: AiContentFile):
            pc_logging.debug("Content: %s", content)
            if content.is_image:
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:%s;base64,%s"
                        % (
                            mimetypes.guess_type(content.filename, strict=False)[0],
                            base64.b64encode(Path(content.filename).read_bytes()).decode(),
                        ),
                        "detail": "high",
                    },
                }
            if content.is_pdf:
                try:
                    import PyPDF2

                    with open(content.filename, "rb") as file:
                        reader = PyPDF2.PdfReader(file)
                        text = ""
                        for page in reader.pages:
                            text += page.extract_text()
                        return text
                except ImportError:
                    pc_logging.error("Install PyPDF2 if you want to use PDF files")
                    return "FAILED-TO-INSERT-PDF-CONTENT"

            return "FILE-TYPE-NOT-SUPPORTED"

        content_parts, content_inserts = self.process_content(prompt)
        content_inserts = list(map(handle_content, content_inserts))
        content = []
        for i in range(len(content_parts)):
            content.append({"type": "text", "text": content_parts[i]})
            if i < len(content_inserts):
                content.append(content_inserts[i])

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
        pc_logging.debug("Params: %s", str(params))

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
